"""jwzthreading.py

Contains an implementation of an algorithm for threading mail
messages, as described at http://www.jwz.org/doc/threading.html.

To use:

  Create a bunch of Message instances, one per message to be threaded,
  filling in the .subject, .message_id, and .references attributes.
  You can use the .message attribute to record the RFC-822 message object,
  or some other piece of information for your own purposes.

  Call the thread() function with a list of the Message instances.

  You'll get back a {subject line -> Container} dictionary; each
  container may have a .children attribute giving descendants of each
  message.  You'll probably want to sort these children by date, subject,
  or some other criterion.

Copyright (c) 2003-2010, A.M. Kuchling.

This code is under a BSD-style license; see the LICENSE file for details.

"""

import re
from collections import deque

__all__ = ['Message', 'make_message', 'thread']

class Container:
    """Contains a tree of messages.

    Instance attributes:
      .message : Message
        Message corresponding to this tree node.  This can be None,
        if a Message-Id is referenced but no message with the ID is
        included.

      .children : [Container]
        Possibly-empty list of child containers.

      .parent : Container
        Parent container; may be None.
    """

    #__slots__ = ['message', 'parent', 'children', 'id']
    def __init__ (self):
        self.message = self.parent = None
        self.children = []

    def __repr__ (self):
        return '<%s %x: %r>' % (self.__class__.__name__, id(self),
                                self.message)

    def is_dummy (self):
        return self.message is None

    def add_child (self, child):
        ##print "Assigning: "
        ##print_container(child, 0, True)
        ##print "as children of: "
        ##print_container(self, 0, True)

        if child.parent:
            child.parent.remove_child(child)
        self.children.append(child)
        child.parent = self

    def remove_child (self, child):
        self.children.remove(child)
        child.parent = None

    def has_descendant (self, ctr, seen=[]):
        """(Container): bool

        Returns true if 'ctr' is a descendant of this Container.
        """
        # To avoid recursing indefinitely, we'll do a depth-first search;
        # 'seen' tracks the containers we've already seen, and 'stack'
        # is a deque containing containers that we need to look at.
        seen.append(self)

        for c in self.children:
            if c in seen:
                continue

            if c is ctr:
                return True

            r = c.has_descendant(ctr, seen)
            if r:
                return True

        return False

    def is_related(self, ctr):
        """(Container): bool

        Returns true if 'ctr' is a ascendant of this Container.
        """
        # To avoid recursing indefinitely, we'll do a depth-first search;
        # 'seen' tracks the containers we've already seen, and 'stack'
        # is a deque containing containers that we need to look at.
        node = self

        # Go up
        while node.parent is not None:
            if node is ctr:
                return True

            node = node.parent

        # Search down
        if node.has_descendant(ctr):
            return True

        return False



    def purge(self, prev=None):
        if prev is None:
            prev = {self: True}
        else:
            prev[self] = True

        for c in self.children:
            if c in prev:
                print_container(c, 0, True)
                self.remove_child(c)
            else:
                c.purge(prev)


    def __len__(self, prev=None):
        if prev is None:
            prev = {self: True}
        else:
            prev[self] = True

        count = 1
        for c in self.children:
            if c in prev:
                #print "BUG: LOOP DETECTED"
                #print_container(c, 10, True)
                # TODO: Fix this hack
                self.remove_child(c)
            else:
                count += c.__len__(prev)
        return count

def uniq(alist):
    set = {}
    return [set.setdefault(e,e) for e in alist if e not in set.keys()]

msgid_pat = re.compile('<([^>]+)>')
restrip_pat = re.compile("""(
  (Re(\[\d+\])?:) | (\[ [^]]+ \])
\s*)+
""", re.I | re.VERBOSE)

def make_message (msg):
    """(msg:rfc822.Message) : Message
    Create a Message object for threading purposes from an RFC822
    message.
    """
    new = Message(msg)

    m = msgid_pat.search(msg.get("Message-ID", ""))
    if m is None:
        raise ValueError("Message does not contain a Message-ID: header")

    new.message_id = m.group(1)

    # Get list of unique message IDs from the References: header
    refs = msg.get("References", "")
    new.references = msgid_pat.findall(refs)
    new.references = uniq(new.references)
    new.subject = msg.get('Subject', "No subject")

    # Get In-Reply-To: header and add it to references
    in_reply_to = msg.get("In-Reply-To", "")
    m = msgid_pat.search(in_reply_to)
    if m:
        msg_id = m.group(1)
        if msg_id not in new.references:
            new.references.append(msg_id)

    return new

class Message (object):
    """Represents a message to be threaded.

    Instance attributes:
    .subject : str
      Subject line of the message.
    .message_id : str
      Message ID as retrieved from the Message-ID header.
    .references : [str]
      List of message IDs from the In-Reply-To and References headers.
    .message : any
      Can contain information for the caller's use (e.g. an RFC-822 message object).

    """
    __slots__ = ['message', 'message_id', 'references', 'subject', 'message_info']

    def __init__(self, msg=None):
        self.message = msg
        self.message_id = None
        self.references = []
        self.subject = None
	self.message_info = None

    def __repr__ (self):
        return '<%s: %r>' % (self.__class__.__name__, self.message_id)

def prune_container (container):
    """(container:Container) : [Container]
    Recursively prune a tree of containers, as described in step 4
    of the algorithm.  Returns a list of the children that should replace
    this container.
    """

    # Prune children, assembling a new list of children
    new_children = []

    ##old_children = container.children[:]

    for ctr in container.children[:]:
        L = prune_container(ctr)
        new_children.extend(L)
        container.remove_child(ctr)

    for c in new_children:
        container.add_child(c)

    ##if new_children != old_children:
    ##    print 'Children for ' + repr(container) + 'Changed'
    ##    print 'OLD children:'
    ##    for ctr in old_children:
    ##        print_container(ctr, 0, True)
    ##    print 'NEW children:'
    ##    for ctr in container.children[:]:
    ##        print_container(ctr, 0, True)

    if (container.message is None and
        len(container.children) == 0):
        # 4.A: nuke empty containers
        return []
    elif (container.message is None and
          (len(container.children)==1 or
           container.parent is not None)):
        # 4.B: promote children
        L = container.children[:]
        ##print "Promoting "+repr(len(container.children))+" children"
        for c in L:
            container.remove_child(c)
        return L
    else:
        # Leave this node in place
        return [container]


def thread (msglist):
    """([Message]) : {string:Container}

    The main threading function.  This takes a list of Message
    objects, and returns a dictionary mapping subjects to Containers.
    Containers are trees, with the .children attribute containing a
    list of subtrees, so callers can then sort children by date or
    poster or whatever.
    """

    id_table = {}
    for msg in msglist:
        # 1A
        this_container = id_table.get(msg.message_id, None)
        if this_container is not None:
            this_container.message = msg
        else:
            this_container = Container()
            this_container.message = msg
            id_table[msg.message_id] = this_container

        # 1B
        prev = None
        for ref in msg.references:
            ## print "Processing reference for "+repr(msg.message_id)+": "+repr(ref)
            container = id_table.get(ref, None)
            if container is None:
                container = Container()
                container.message_id = ref
                id_table[ref] = container

            if prev is not None:
                #If they are already linked, don't change the existing links.
                if container.parent is not None:
                    pass
                # Don't add link if it would create a loop
                elif container is this_container or prev.has_descendant(container) or container.has_descendant(container):
                    pass
                else:
                    prev.add_child(container)

            prev = container
            ## print "Finished processing reference for "+repr(msg.message_id)+", container now: "
            ## print_container(container, 0, True)
        #1C
        if prev is not None:
            ##print "Setting parent of "+repr(this_container)+", to last reference: " + repr (prev)
            prev.add_child(this_container)
        else:
            if(this_container.parent):
                this_container.parent.remove_child(this_container)
        

    # 2. Find root set
    root_set = [container for container in id_table.values()
                if container.parent is None]
    
    # 3. Delete id_table
    del id_table

    # 4. Prune empty containers
    for container in root_set:
        assert container.parent == None


    ##print 'before'
    ##for ctr in root_set:
    ##    print_container(ctr, 0, True)

    new_root_set = []
    for container in root_set:
        L = prune_container(container)
        new_root_set.extend(L)

    root_set = new_root_set

    ##print '\n\nafter'
    ##for ctr in root_set:
    ##    print_container(ctr, 0, True)

    # 5. Group root set by subject
    subject_table = {}
    for container in root_set:
        if container.message:
            subj = container.message.subject
        else:
            c = container.children[0]
            subj = container.children[0].message.subject

        subj = restrip_pat.sub('', subj)
        if subj == "":
            continue

        existing = subject_table.get(subj, None)
        if (existing is None or
            (existing.message is not None and
             container.message is None) or
            (existing.message is not None and
             container.message is not None and
             len(existing.message.subject) > len(container.message.subject))):
            subject_table[subj] = container

    # 5C
    for container in root_set:
        if container.message:
            subj = container.message.subject
        else:
            subj = container.children[0].message.subject

        subj = restrip_pat.sub('', subj)
        ctr = subject_table.get(subj)
        if ctr is None or ctr is container:
            continue
        if ctr.is_dummy() and container.is_dummy():
            for c in ctr.children:
                container.add_child(c)
        elif ctr.is_dummy() or container.is_dummy():
            if ctr.is_dummy():
                ctr.add_child(container)
            else:
                container.add_child(ctr)
        elif len(ctr.message.subject) < len(container.message.subject):
            # ctr has fewer levels of 're:' headers
            ctr.add_child(container)
        elif len(ctr.message.subject) > len(container.message.subject):
            # container has fewer levels of 're:' headers
            container.add_child(ctr)
        else:
            new = Container()
            new.add_child(ctr)
            new.add_child(container)
            subject_table[subj] = new

    return subject_table


def print_container(ctr, depth=-1, debug=0, indent=0):
    import sys
    if depth == 0:
        return

    sys.stdout.write(' ' * indent)
    if debug:
        # Printing the repr() is more useful for debugging
        sys.stdout.write(repr(ctr) + ' ' + repr(ctr.message and ctr.message.subject))
    else:
        sys.stdout.write(repr(ctr.message and ctr.message.subject))

    sys.stdout.write("\n")
    for c in ctr.children:
        print_container(c, depth-1, debug, indent+1)


def main():
    import mailbox

    print('Reading input file...')
    f = open("mbox", 'rb')
    mbox = mailbox.UnixMailbox(f)
    msglist = []
    while 1:
        msg = mbox.next()
        if msg is None:
            break
        m = make_message(msg)
        msglist.append(m)
    f.close()

    print('Threading...')
    subject_table = thread(msglist)

    # Output
    L = subject_table.items()
    L.sort()
    for subj, container in L:
        print_container(container)

if __name__ == "__main__":
    main()

