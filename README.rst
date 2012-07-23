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
