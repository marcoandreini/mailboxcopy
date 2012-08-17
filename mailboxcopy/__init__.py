# -*- coding: utf-8 -*-
#
# Copyright (C) 2012 Marco Andreini
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#

import email
import argparse
import logging

from collections import namedtuple
from urlparse import urlparse
from urlparse import unquote

from concurrent import futures
from imapclient import IMAPClient
from imapclient import RECENT


Message = namedtuple('Message', 'id size folder body flags date')

def chunk(ulist, step):
    return map(lambda i: ulist[i:i+step],  xrange(0, len(ulist), step))

def sizeof(num):
    for x in ('bytes','KiB','MiB','GiB','TiB'):
        if num < 1024.0:
            return "%3.1f%s" % (num, x)
        num /= 1024.0


class IMAPClientExt(IMAPClient):

    def __init__(self, urlstring, executor, buffer_size):
        url = urlparse(urlstring)
        if not url.scheme in ("imap", "imaps"):
            raise Exception("invalid scheme: " + urlstring)
        super(IMAPClientExt, self).__init__(url.hostname, port=url.port,
                                            ssl=url.scheme.endswith('s'))
        logging.debug("scheme=%s, host=%s, port=%s, username=%s, password=<omitted>",
                  url.scheme, url.hostname, url.port, url.username)
        self.login(unquote(url.username), unquote(url.password))
        path = url.path[:-1] if len(url.path) > 0 \
            and url.path.endswith('/') else url.path
        if path:
            self.select_folder(path)
        self.executor = executor

        self.buffer_size = buffer_size
        self.to_complete = 0
        self.writes = []

    def fetch_all(self, data):
        """
        fetch all (from current folder) messages

        """

        messages = self.search()
        result = {}
        for msgs in chunk(messages, 1000):
            result.update(self.fetch(msgs, data))
        return result

    def write(self, message):

        logging.debug("write %s (%s) to destination folder %s -> %s",
                      message.id, sizeof(message.size), message.folder, message.date)
        try:
            self.append(message.folder, message.body, message.flags, message.date)
        except Exception as e:
            logging.warn("write error for %s: %s", message.id, e)

    def end_of_write(self, future):
        self.to_complete -= 1

    def async_write(self, message):
        self.to_complete += 1
        future = self.executor.submit(self.write, message)
        future.add_done_callback(self.end_of_write)
        self.writes.append(future)

    def wait_partial(self):
        while self.to_complete >= self.buffer_size:
            t = futures.wait(self.writes, 5.0, futures.FIRST_COMPLETED)
            for done in t.done:
                self.writes.remove(done)
            # logging.debug("%d writes waiting", len(t.not_done))

    def wait_writes(self):
        if self.writes:
            futures.wait(self.writes)


HEADERS = 'BODY[HEADER.FIELDS (MESSAGE-ID)]'
FLAGS ='FLAGS'
BODY_PEEK ='BODY.PEEK[]'
BODY = 'BODY[]'
RFC822_SIZE = 'RFC822.SIZE'
INTERNALDATE ='INTERNALDATE'
MESSAGE_ID = 'Message-ID'

MessageHeader = namedtuple('MessageHeader', 'id size')

class MessageParser:
    """
    sanitize imap fetch response

    """

    def __init__(self):
        self.header_parser = email.Parser.HeaderParser()

    def header(self, data):
        """

        >>> mp = MessageParser()
        >>> data = {'BODY[HEADER.FIELDS ("MESSAGE-ID")]': 'Message-id:\\r\\n <ciaociao@ciao.it>\\r\\n', 'RFC822.SIZE': 123}
        >>> header = mp.header(data)
        >>> header.size
        123
        >>> header.id
        '<ciaociao@ciao.it>'

        """

        data = dict((k.replace('"', ''), v) for k, v in data.items())
        return MessageHeader(id=self.header_parser.parsestr(data[HEADERS]).get(MESSAGE_ID).strip(),
                             size=data[RFC822_SIZE])

    def message(self, folder, msgid, data):
        """

        >>> from datetime import datetime
        >>> mp = MessageParser()
        >>> data = {'FLAGS': (r'\Recent', 'altro'), 'RFC822.SIZE': 456, 'BODY[]': 'xyz', 'INTERNALDATE': datetime.now()}
        >>> message = mp.message('myfolder', '<mymessageid@test.it>', data)
        >>> message.size
        456
        >>> message.folder
        'myfolder'
        >>> message.body
        'xyz'
        >>> message.id
        '<mymessageid@test.it>'
        >>> isinstance(message.date, datetime)
        True
        >>> message.flags
        ['altro']


        """

        return Message(id=msgid, size=data[RFC822_SIZE], body=data[BODY],
                       flags=[f for f in data[FLAGS] if f != RECENT],
                       folder=folder, date=data[INTERNALDATE])


class ExcludeList:

    def __init__(self, excludes):
        # sanitized
        self.excludes = [ExcludeList.slashify(e) for e in excludes]

    @staticmethod
    def slashify(value):
        return value if value.endswith('/') else value +'/'

    def __call__(self, name):
        """

        >>> is_excluded = ExcludeList(['a', 'b/b1', 'c/c1/c2'])
        >>> is_excluded('a')
        True
        >>> is_excluded('a/test')
        True
        >>> is_excluded('a1')
        False
        >>> is_excluded('b1')
        False
        >>> is_excluded('b/b')
        False
        >>> is_excluded('b/b1')
        True
        >>> is_excluded('c/c1/c2/')
        True
        >>> is_excluded('c/c1')
        False
        >>> is_excluded('c/c1/c2/c3')
        True

        """
        name = ExcludeList.slashify(name)
        return any(name.startswith(e) for e in self.excludes)


class TestAction(argparse._VersionAction):

    def __call__(self, parser, namespace, values, option_string=None):
        # setattr(namespace, self.dest, values)
        import doctest
        doctest.testmod() #verbose=True)
        parser.exit()


def main():

    message_parser = MessageParser()
    pre_data = [HEADERS, RFC822_SIZE, INTERNALDATE]

    folder_mapping = {'INBOX/Sent': 'Sent'}

    parser = argparse.ArgumentParser(description="imap mailbox copy")
    parser.add_argument("-v", "--verbose", action="store_true",
                        help="increase output verbosity")
    parser.add_argument("-t", "--test", action=TestAction,
                        help="run doctest and exit")
    parser.add_argument("-d", "--dry-run", action="store_true",  dest="dry_run",
                        help="dry run, create folders only")
    parser.add_argument("-x", "--exclude", action="append",
                        help="exclude folder(s)")
    parser.add_argument("-l", "--limit-size", dest="limit_size", type=int,
                        help="skip messages with size greater")
    parser.add_argument("-b", "--buffer-size", dest="buffer_size", type=int, default=10,
                        help="read buffer size before async write, in number of messages")
    parser.add_argument("source", help="source, like imap://marco:passwd@sitename.it/INBOX")
    parser.add_argument("destination", help="destination, like imaps://ma:mypasswd@othersitename.it/")
    args = parser.parse_args()

    if args.verbose:
        logging.basicConfig(level=logging.DEBUG)
    else:
        logging.basicConfig(level=logging.INFO)

    is_excluded = ExcludeList(args.exclude)

    executor = futures.ThreadPoolExecutor(1)
    source = IMAPClientExt(args.source, executor, args.buffer_size)
    destination = IMAPClientExt(args.destination, executor, args.buffer_size)
    bytes_total = 0
    for folder in source.list_folders():
        delimiter = folder[1]
        src_name = folder[2]
        if is_excluded(src_name if delimiter == '/' else src_name.replace(delimiter, '/')):
            logging.info("skipped source folder %s", src_name)
            continue

        logging.debug("processing source folder %s", src_name)
        source.select_folder(src_name, readonly=True)
        dst_name = folder_mapping[src_name] if folder_mapping.has_key(src_name) else src_name
        dst_exists = destination.folder_exists(dst_name)
        if not dst_exists:
            logging.debug("folder %s not exists in destination", dst_name)
            if not args.dry_run:
                res = destination.create_folder(dst_name)
                logging.debug("created destination folder %s", res)
        if dst_exists:
            destination.select_folder(dst_name)

        src_result = source.fetch_all(pre_data)
        if len(src_result) == 0:
            logging.debug("%s is empty, skipped", src_name)
            continue
        else:
            logging.debug("found %d messages in source / %s", len(src_result), src_name)

        dst_sizes = {}
        dst_msg_ids = set()
        if dst_exists:
            dst_result = destination.fetch_all(pre_data)
            logging.debug("fetched %d message-id from %s in destination", len(dst_result), dst_name)

            for data in dst_result.itervalues():
                dst_header = message_parser.header(data)
                dst_msg_ids.add(dst_header.id)

                try:
                    dst_sizes[dst_header.size].append(dst_header.id)
                except KeyError:
                    dst_sizes[dst_header.size] = [dst_header.id]

        msg_copied = 0
        bytes_copied = 0
        skipped = 0

        for mid, data in src_result.iteritems():
            src_header = message_parser.header(data)
            if not src_header.id in dst_msg_ids:
                if not args.limit_size is None and src_header.size > args.limit_size:
                    logging.info("skipped message %s in %s (%s > limit-size)",
                                 src_header.id, src_name, sizeof(src_header.size))
                else:
                    msg_copied += 1
                    bytes_copied += src_header.size

                    logging.debug("read %s (%s) from source", src_header.id,
                                  sizeof(src_header.size))
                    if not args.dry_run:
                        destination.wait_partial()
                        message = message_parser.message(dst_name, src_header.id,
                                                         source.fetch(mid, [FLAGS, BODY_PEEK, RFC822_SIZE, INTERNALDATE])[mid])
                        destination.async_write(message)
            else:
                skipped += 1

        if skipped > 0:
            logging.debug("skipped %d previously copied messages", skipped)

        logging.debug("waiting writes to destination folder %s", dst_name)
        destination.wait_writes()
        if msg_copied > 0:
            logging.info("copied %d messages (%s) from source %s to destination %s",
                         msg_copied, sizeof(bytes_copied), src_name, dst_name)
        bytes_total += bytes_copied
    logging.info("copied %s", sizeof(bytes_total))
    source.logout()
    destination.logout()

if __name__ == '__main__':
    main()
