===========
MailboxCopy
===========

About
=====

MailboxCopy is a command-line mailbox imap copy tool, written in python and based on
IMAPClient.

Main features:

 * idempotent: run several times with no changes, does not make unnecessary copies
 * imap or imaps
 * optional list of excluded folder
 * optional limit size for messages
 * "dry run" for testing purpose.


Installation
============

You can use virtualenv in order to setup this application::

  virtualenv --no-site-packages mailboxcopyenv
  . mailboxcopyenv/bin/activate

Single command, using distribute/pip/... ::

  python setup.py install

Help command line parameters are provided with the -h or --help parameter.


Usage
====

In order to specify the '@' in username (as 'john@example.cc') on command-line
you must replace with urlquoted version (i.e. imaps://john%40example.cc:pass@imap.example.cc').
In order to map all inner folder to another folder insert / at the end of foldername, like:
 -m INPUT/:other     map all sub-folder of INPUT to be inner of "other" folter
 -m INPUT/:          map all sub-folder of INPUT to be inner of IMAP root folder
