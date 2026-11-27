#!/usr/bin/env python3
"""Refuse a release while a pull request merged since the last release lacks a category.

Run this before choosing a release's version. By default it asks GitHub, through
the gh command, for the latest published release and the pull requests merged
into main after it. --input reads the same pull request list from a file, or
from standard input with '-', so the check also runs offline. Each entry needs
number, title, labels and mergedAt, as `gh pr list --json` prints them.
"""
import argparse
import json
from pathlib import Path
import subprocess
import sys

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[2]
CATEGORIES = ROOT / '.agents/tools/release-categories.txt'
# gh pr list returns at most this many; a full page may hide older pull requests.
LIMIT = 1000


def categories():
    lines = [line for line in CATEGORIES.read_text().splitlines() if line and not line.startswith('#')]
    names = [line.split()[0] for line in lines]
    if not names:
        raise ValueError(f'no release categories could be read from {CATEGORIES}')
    return names, lines


def gh(*args):
    result = subprocess.run(['gh', *args], cwd=ROOT, text=True, capture_output=True)
    if result.returncode != 0:
        raise ValueError('gh ' + ' '.join(args[:2]) + ' failed: ' + result.stderr.strip())
    return json.loads(result.stdout or 'null')


def last_release():
    releases = gh('release', 'list', '--exclude-drafts', '--limit', '1', '--json', 'tagName,publishedAt')
    if not releases:
        return None, None
    return releases[0]['tagName'], releases[0]['publishedAt']


def merged_pull_requests():
    found = gh('pr', 'list', '--state', 'merged', '--base', 'main', '--limit', str(LIMIT),
               '--json', 'number,title,labels,mergedAt')
    if len(found) >= LIMIT:
        raise ValueError(f'GitHub returned {LIMIT} merged pull requests, so the list may be incomplete; '
                         'pass --input with the complete list instead')
    return found


def read_input(source):
    text = sys.stdin.read() if source == '-' else Path(source).read_text()
    found = json.loads(text)
    if not isinstance(found, list):
        raise ValueError('--input must hold a JSON list of pull requests')
    return found


def label_names(pull_request):
    return [label['name'] if isinstance(label, dict) else str(label) for label in pull_request.get('labels') or []]


def main(argv):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--input', help="pull requests as gh pr list --json prints them; '-' reads standard input")
    parser.add_argument('--since', help='ISO 8601 time of the last release; overrides the time GitHub reports')
    options = parser.parse_args(argv)

    names, lines = categories()
    tag = None
    since = options.since
    if options.input:
        pull_requests = read_input(options.input)
    else:
        if since is None:
            tag, since = last_release()
        pull_requests = merged_pull_requests()

    # GitHub prints UTC times with a Z suffix, so text order is time order.
    if since:
        pull_requests = [p for p in pull_requests if (p.get('mergedAt') or '') > since]
    pull_requests.sort(key=lambda p: p.get('number', 0))
    scope = f'since {tag} ({since})' if tag else (f'since {since}' if since else 'so far, with no published release yet')

    missing = [p for p in pull_requests if not set(label_names(p)) & set(names)]
    if missing:
        print(f'The release cannot proceed: {len(missing)} pull request(s) merged {scope} '
              'have no release category, so nobody has decided what they mean for the version.\n',
              file=sys.stderr)
        for p in missing:
            print(f"  #{p.get('number')} {p.get('title', '')}", file=sys.stderr)
        print('\nAdd one category to each, for example:\n', file=sys.stderr)
        print(f"  gh pr edit {missing[0].get('number')} --add-label <category>\n", file=sys.stderr)
        print('The categories are:\n', file=sys.stderr)
        for line in lines:
            print('  ' + line, file=sys.stderr)
        print('\nThen run this check again.', file=sys.stderr)
        return 1

    print(f'Every pull request merged {scope} has a release category ({len(pull_requests)} checked):')
    for p in pull_requests:
        chosen = ', '.join(n for n in label_names(p) if n in names)
        print(f"  #{p.get('number')} {p.get('title', '')}: {chosen}")
    return 0


if __name__ == '__main__':
    try:
        sys.exit(main(sys.argv[1:]))
    except (ValueError, OSError, KeyError, TypeError) as exc:
        print('error: ' + str(exc), file=sys.stderr)
        sys.exit(2)
