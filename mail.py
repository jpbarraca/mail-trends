#Modified by Joao Paulo Barraca <jpbarraca@ua.pt>

import imaplib
import logging
import random

import cache
import messageinfo
import stringscanner
import os
import email
import time
import re

from cStringIO import StringIO

class Mail(object):
    def __init__(self, server, use_ssl, username, password,
            record=False, replay=False, max_messages=-1, random_subset=False):
        self.__server = server
        self.__username = username
        self.__record = record
        self.__replay = replay
        self.__max_messages = max_messages
        self.__random_subset = random_subset

        self.__current_mailbox = None

        if record or replay:
            self.__cache = cache.FileCache()

        imap_constructor = use_ssl and imaplib.IMAP4_SSL or imaplib.IMAP4

        logging.info("Connecting")

        self.__mail = imap_constructor(server)

        logging.info("Logging in")

        self.__mail.login(username, password)

    def GetMailboxes(self):
        logging.info("Getting mailboxes")

        r, mailboxes_data = self.__mail.list()
        self.__AssertOk(r)

        mailboxes = []
        for mailbox_data in mailboxes_data:
            s = stringscanner.StringScanner(mailbox_data)

            attributes = s.ConsumeValue()
            s.ConsumeAll(" ")
            delimiter = s.ConsumeValue()
            s.ConsumeAll(" ")
            name = s.ConsumeValue()

            logging.info("Found %s",name)
            mailboxes.append(name)

        return mailboxes

    def SelectMailbox(self, mailbox):
        logging.info("Selecting mailbox '%s'", mailbox)
        r, data = self.__mail.select(mailbox)
        self.__AssertOk(r)

        self.__current_mailbox = mailbox

    def GetMessageIds(self):
        message_infos = self.__UidFetch("ALL", "(INTERNALDATE RFC822.SIZE)")

        return [m.GetMessageId() for m in message_infos]

    def GetMessageInfos(self):
        return self.__UidFetch(
                "ALL",
                "(UID FLAGS INTERNALDATE RFC822.SIZE RFC822.HEADER)",
                self.__max_messages)

    def Logout(self):
        logging.info("Logging out")

        self.__mail.close()
        self.__mail.logout()

    def __UidFetch(self, search_criterion, fetch_parts, max_fetch=-1):
        logging.info("Fetching message infos")

        logging.info("  Fetching message list")
        data = self.__UidCommand("SEARCH", search_criterion)

        message_ids = data[0].split()

        logging.info("  %d messages were listed" % len(message_ids))

        if max_fetch != -1 and len(message_ids) > max_fetch:
            if self.__random_subset:
                # Pick random sample when there is a max, so that we get more
                # interesting data. However, use the same seed so that runs will be
                # deterministic and we can take advantage of record/replay
                random.seed(len(message_ids))

                # If possible, select a random sample from a recent subset of messages
                subset_size = max_fetch * 30
                if len(message_ids) > subset_size:
                    message_ids = message_ids[-subset_size - 1:-1]

                message_ids = random.sample(message_ids, max_fetch)
            else:
                message_ids = message_ids[-max_fetch - 1:-1]

        message_infos = []

        # Fetch in smaller chunks, so that record/replay can be used when fetches
        # fail (to allow caching of successful chunks) and to have better progress
        # display
        chunk_size = fetch_parts.find("HEADER") != -1 and 1000 or 100000

        for i in xrange(0, len(message_ids), chunk_size):
            chunk_start = i
            chunk_end = i + chunk_size
            if chunk_end > len(message_ids):
                chunk_end = len(message_ids)

            chunk_message_ids = message_ids[chunk_start:chunk_end]

            logging.info("  Fetching info for %d messages (%d/%d)",
                    len(chunk_message_ids),
                    chunk_end,
                    len(message_ids))

            fetch_reply = self.__UidCommand(
                    "FETCH",
                    ",".join(chunk_message_ids),
                    fetch_parts)

            logging.info("  Parsing replies")

            message_infos.extend(self.__ParseFetchReply(fetch_reply))

        logging.info("  Got %d message infos" % len(message_infos))

        return message_infos

    def __UidCommand(self, command, *args):
        if self.__record or self.__replay:
            cache_key = "%s-%s-%s-%s-%s" % (
                    self.__server, self.__username, self.__current_mailbox,
                    command, " ".join(args))

        if self.__replay:
            cached_response = self.__cache.Get(cache_key)
            if cached_response:
                return cached_response

        r, data = self.__mail.uid(command, *args)
        self.__AssertOk(r)

        if self.__record:
            self.__cache.Set(cache_key, data)

        return data

    def __ParseFetchReply(self, fetch_reply):
        s = stringscanner.StringScanner(fetch_reply)
        message_infos = []

        while s.Peek():
            current_message_info = messageinfo.MessageInfo()

            # The sequence ID is first, with all the data in parentheses
            sequence_id = s.ReadUntil(" ")
            s.ConsumeAll(" ")

            s.ConsumeChar("(")
            while s.Peek() != ")":
                s.ConsumeAll(" ")
                name = s.ReadUntil(" ")
                s.ConsumeAll(" ")
                value = s.ConsumeValue()
                current_message_info.PopulateField(name, value)
            if(current_message_info.HasDate()):
                message_infos.append(current_message_info)
            if s.Peek():
                s.ConsumeChar(")")

        return message_infos

    def __AssertOk(self, response):
            assert response == "OK"


class MaildirInfo(object):
    """
    A semi-greedy Maildir crawler

    This crawler is *extremely* relaxed about the Maildir spec.
    It considers every subfolder with (sub,new,cur) folders as
    a valid Maildir, and it recursevely walks the tree. A few
    notes:

    1. This SHOULD handle both Maildir and Maildir++
    2. This SHOULD also handle weird non conformant Maildir
        as long as (cur,new,tmp) exist
    3. This does not gather flags (i.e. New or Read)
    4. Dates might be different from the dates you see in IMAP
    5. This will wall all folders recursively, so if you point
         it to the root it will index all Maildirs in your hard drive.
    6. As is this is slower than the mail.Mail class because we read
         the entire mail contents into memory.

    """
    def __init__(self, path):
        self.path = os.path.expanduser(path)
        self.mailboxes = {}

        for dirname, dirnames, filenames in os.walk(self.path):

            for subdirname in dirnames:
                folder = os.path.join(dirname, subdirname)

                if os.path.isdir(os.path.join(folder, 'new')) and \
                        os.path.isdir(os.path.join(folder, 'cur')) and \
                        os.path.isdir(os.path.join(folder, 'tmp')):

                    self.mailboxes[folder] = []
                    logging.info("Found %s", folder)

            for filename in filenames:
                box = os.path.dirname(dirname)
                if not filename.startswith('.') and box in self.mailboxes:
                    path = os.path.join(dirname, filename )
                    self.mailboxes[box].append(path)

        if not self.mailboxes:
                raise RuntimeError("No mailboxes were found")
        self.__current_mailbox = None

    def GetMailboxes(self):
        "Return list of mailboxes in this maildir"
        return self.mailboxes.keys()

    def SelectMailbox(self, mailbox):
        "Set the current mailbox"

        logging.info("Selecting mailbox '%s'", mailbox)
        self.__current_mailbox = mailbox

    def GetMessageInfos(self):
        """
        Return a list of MessageInfo objects, one per message

        If the current mailbox has been selected, only mails from
        that mailbox are selected, otherwise all mails are returned.
        """

        if self.__current_mailbox and self.mailboxes.has_key(self.__current_mailbox):
            boxes = [self.__current_mailbox]
        else:
            boxes = self.GetMailboxes()

        info = []
        for mbox in boxes:
            for path in self.mailboxes[mbox]:
                mi = messageinfo.MessageInfo()
                try:
                    fd = open(path, "r")
                    fd.readline()

                    headers = StringIO()
                    bytes_read = 0
                    while True:
                        chunk = fd.read(1024)
                        if chunk == '':
                            break

                        bytes_read += len(chunk)
                        headers.write(chunk)
                        if '\n\n' in chunk or bytes_read >= 100000:
                            break
                    fd.close()

                    msg = email.message_from_string(headers.getvalue())

                    # FIXME: there has to be a better way to do this
                    # e.g. Just read the headers and stat the file
                    mi.PopulateField('RFC822.SIZE', os.stat(path).st_size )
                    mi.PopulateField('RFC822.HEADER', self.__BuildHeader(msg) )

                    if "Date" not in msg:
                        print("Unable to parse mail, skipping ", path)
                        continue

                    date = email.utils.parsedate_tz(msg["Date"])
                    t = time.gmtime(email.utils.mktime_tz(date))
                    maildate = time.strftime("%d-%b-%Y %H:%M:%S", t) + ' %+05d' % (date[9] / 3600)
                    mi.PopulateField('INTERNALDATE', maildate)

                    info.append(mi)
                except:
                        logging.info("ERROR: Unable to parse file: %s",path)

        return info

    def __BuildHeader(self, msg):
        """
        From a dict of header name/value build the
        email header
        """
        header = ''
        for k in msg.keys():
            header += '%s: %s\r\n' % (k, msg[k])
        return header

    def Logout(self):
        "Do nothing"
        pass


class MailBoxPackageInfo(object):
    """
    A semi-greedy Mailbox Package crawler

    This crawler is *extremely* relaxed about the MailBoxPackage spec.
    It considers every subfolder with extension .mbox folders as
    a valid MailBoxPackage, and it recursevely walks the tree parsing all
    .emlx files found. A few
    notes:

    1. This does not gather flags (i.e. New or Read)
    2. Dates might be different from the dates you see in IMAP
    3. As is this is slower than the mail.Mail class because we read
         the entire mail contents into memory.

    """
    def __init__(self, path):
        import re

        self.path = os.path.expanduser(path)
        self.mailboxes = {}
        validDir = re.compile(".*\/[A-Z0-9]+\-[A-Z0-9]+\-[A-Z0-9]+\-[A-Z0-9]+\-[A-Z0-9]+\/Data\/.*\/Messages")

        for dirname, dirnames, filenames in os.walk(self.path):
            for subdirname in dirnames:
                folder = os.path.join(dirname, subdirname)
                if os.path.isdir(folder) and folder.endswith(".mbox"):
                    self.mailboxes[folder] = []
                    logging.info("Found %s", folder)

            for filename in filenames:
                logging.debug("Testing %s", dirname)

                if not validDir.match(dirname):
                        logging.debug("Ignoring %s", dirname)
                        continue

                box = dirname
                while os.path.exists(box) and not box.endswith(".mbox"):
                    box = os.path.dirname(box)

                if not filename.startswith('.') and filename.endswith(".emlx") and box in self.mailboxes:
                    logging.debug("Adding file %s/%s to box %s",dirname,filename,box)
                    path = os.path.join(dirname, filename)
                    self.mailboxes[box].append(path)

        if not self.mailboxes:
                raise RuntimeError("No mailboxes were found")
        self.__current_mailbox = None

    def GetMailboxes(self):
        "Return list of mailboxes in this maildir"
        return self.mailboxes.keys()

    def SelectMailbox(self, mailbox):
        "Set the current mailbox"

        logging.info("Selecting mailbox '%s'", mailbox)
        self.__current_mailbox = mailbox

    def GetMessageInfos(self):
        """
        Return a list of MessageInfo objects, one per message

        If the current mailbox has been selected, only mails from
        that mailbox are selected, otherwise all mails are returned.
        """

        if self.__current_mailbox and self.mailboxes.has_key(self.__current_mailbox):
            boxes = [self.__current_mailbox]
        else:
            boxes = self.GetMailboxes()

        info = []
        for mbox in boxes:
            #logging.debug("GetMessages from Mailbox: %s", mbox)
            for path in self.mailboxes[mbox]:
                #logging.debug("ReadMessage: %s", path)

                mi = messageinfo.MessageInfo()
                try:
                    fd = open(path, "r")
                    fd.readline()

                    headers = StringIO()
                    bytes_read = 0
                    while True:
                        chunk = fd.read(1024)
                        if chunk == '':
                            break

                        bytes_read += len(chunk)
                        headers.write(chunk)
                        if '\n\n' in chunk or bytes_read >= 100000:
                            break
                    fd.close()

                    msg = email.message_from_string(headers.getvalue())

                    # FIXME: there has to be a better way to do this
                    # e.g. Just read the headers and stat the file
                    mi.PopulateField('RFC822.SIZE', os.stat(path).st_size)
                    mi.PopulateField('RFC822.HEADER', self.__BuildHeader(msg))

                    if "Date" not in msg:
                        #logging.info("ERROR: Unable to parse file: %s", path)
                        continue

                    date = email.utils.parsedate_tz(msg["Date"])
                    t = time.gmtime(email.utils.mktime_tz(date))
                    maildate = time.strftime("%d-%b-%Y %H:%M:%S", t) + ' %+05d' % (date[9] / 3600)
                    mi.PopulateField('INTERNALDATE', maildate)

                    info.append(mi)
                except:
                    #logging.info("ERROR: Unable to parse file: %s", path)
                    pass

        return info

    def __BuildHeader(self, msg):
        """
        From a dict of header name/value build the
        email header
        """
        header = StringIO()
        for k in msg.keys():
            if k in ['From', 'Date', 'To', 'Subject', 'Sender', 'Message-ID', 'List-Id']:
                header.write('%s: %s\r\n' % (k, msg[k]))
        return header.getvalue()

    def Logout(self):
        "Do nothing"
        pass





