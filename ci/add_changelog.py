#/usr/bin/env python

import time
import argparse
from string import Template


def main(args):

    t = time.localtime()
    timestamp = time.strftime('%Y%m%d.%H%M%S', t)
    datetime = time.strftime('%a, %d %b %Y %H:%M:%S +9000', t)

    tmpl = Template(open(args.t).read())

    param = {
             'repo': args.r,
             'version': args.v,
             'change': args.c,
             'timestamp': timestamp,
             'datetime': datetime
             }

    f = open(args.f, 'r')
    prev_content =  f.read()
    f.close()

    f = open(args.f, 'w')
    f.write(tmpl.substitute(param))
    f.write(prev_content)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='build deb package')
    parser.add_argument('-r', metavar='Repo', help='repo name', required=True)
    parser.add_argument('-v', metavar='version', help='version', required=True)
    parser.add_argument('-c', metavar='change', help='change entry', required=True)
    parser.add_argument('-f', metavar='file', help='changelog file path', required=True)
    parser.add_argument('-t', metavar='template', help='template file path', required=True)
    args = parser.parse_args()
    main(args)
