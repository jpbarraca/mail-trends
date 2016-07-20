Mail Trends
====

Mail Trends lets you analyze and visualize your email (as extracted from an IMAP server). You can see:

* Distribution of messages by year, month, day, day of week and time of day. 
* Distribution of messages by size and your top 40 largest messages
* The top senders, recipients and mailing lists you're on.
* Distributions of senders, recipients and mailing lists over time
* The distribution of thread lengths and the lists and people that result in the longest threads

![Mail Trends example](mailtrends.png?raw=true "Example output. Runtime:  3616.67s user 67.15s system 98% cpu 1:05:30.53 total")


This package was modified from the original in order to fix some errors, greatly improve its performance, reduce memory consumption, and to add support for a larger amount of servers, and email origins. 

Currently it supports: "Any" IMAP Server, Maildir folders and Mailbox Packages (MacOS Mail.app). 

For GMAIL, it may produce duplicate stats unless you filter results to only consider the "All Mail" folder.

If you have all your IMAP accounts configured in Mail.app, with offline messages, just use ```--mailboxpackage=~/Library/Mail/V3``` and it will process all local and remote folders.

For the original version, please see: http://code.google.com/p/mail-trends/

Original Copyright Mihai Parparita
modified by João Paulo Barraca <jpbarraca@gmail.com> and Rui Ferreira <rferreira@av.it.pt>


Example usage
====

```
./main.py --server=mail.domain.com --username=guest --password=1234 --use_ssl
```

or reading a local Maildir folder

```
./main.py --maildir=~/Mail
```

or reading a Mail.app Mailbox

```
./main.py --mailboxpackage=~/Library/Mail/V3
```
