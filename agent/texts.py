"""Every fixed text the runtime puts before a resident, kept together for the wording guard.

Templates take their fields with `str.format`. The descriptions of the runtime's own tools live
with their specs in `agent.files` and `agent.runtime`.
"""

ABOUT_ME = "# About me, in my own words"
"""Heads the resident's own account of itself, background.md, at the start of its standing text."""

GUIDE = """\
## How you act

You act by name: you walk somewhere with go, speak with say, run a command with shell, read one \
of your files with read_file, and so on. What you think without doing anything is yours alone, \
and nobody hears it. Whenever something happens, you are told the time, where you are and what \
you can do at that moment; what you cannot do just then tells you so when you try.

When you have nothing more to do for now, do nothing more, and time passes until something \
happens: someone speaks to you, something changes around you, or the clock moves on, and you are \
told. If someone speaks to you while you are thinking, you hear it at once.

Of a very long output you see the beginning and the end. When what you carry in mind grows long, \
you write down for yourself what you will want to remember and keep only those notes and the \
last few things that happened; you can do so yourself at any time with compact."""

FILES = """\
## Your files

You keep files of your own: your account of yourself, your journal, whatever you want to keep \
under memory/ (notes, drafts, lists), and your skills under skills/, each a method written down \
so that you can reread it or pass it on. Your files stay with you from day to day, and no one \
else in town reads them. Your account of yourself is background.md, the words about you that \
open all this; they are yours: change them as you change, and what you write there is before \
you from then on.

Read one with read_file, change it with write_file or edit_file, and see what you have with \
list_files. Paths are written like memory/notes.md. The first line of each file in skills/ says \
what it is for."""

SKILLS_READ_ONLY = "You can read the files in skills/ but not change them."

KNOWN_FILES = {"background.md": "your account of yourself, in your own words"}
"""What the files every resident has are for, as the index of files says."""

# Refusals and results of the file tools.
OUTSIDE = (
    "{path} is not one of your own files; yours are background.md and those in memory/ and "
    "skills/. The files of a task's repository you read and change with read_repo_file, "
    "write_repo_file and edit_repo_file."
)
NO_FILE = "There is no file {path}."
A_FOLDER = "{path} is a folder, not a file."
NO_FILES = "There are no files in {path}."
EMPTY_FILE = "{path} is empty."
PART_OF_FILE = "Lines {first} to {last} of {total} in {path}:\n\n{text}"
WROTE = "Wrote {path}."
EDITED = "Changed {path}."
PASSAGE_MISSING = "The passage to replace does not appear in {path}."
PASSAGE_REPEATED = (
    "The passage to replace appears {count} times in {path}; include more of the text around it "
    "so that it appears once."
)
NEEDS = "{name} needs {argument} as {kind}."
TEXT = "text"
NUMBER = "a whole number from 1"

# News that came while the resident was busy, told ahead of what a call came to.
NEWS_AHEAD = "Meanwhile:\n{news}\n\nBack to what you were doing:\n{result}"
NEWS_ITEM = "{hour} — {text}"

# What the runtime itself answers.
UNKNOWN_TOOL = "There is nothing you can do called {name}."
UNREADABLE = "What you meant to do could not be made out, so nothing was done."
FAILED = "This could not be carried out."
NOT_CARRIED_OUT = "Not carried out: something came up first."
CONDENSING = "You stop to write down what you will want to remember."
CUT_OFF = "You broke off above, having gone on too long; nothing in it was done."
SHORTENED = "[... {count} characters left out here ...]"

# Compaction.
NOTES_HEADINGS = (
    "## What I am doing and where I stand",
    "## Facts I must not lose",
    "## Decisions and their reasons",
    "## Open questions",
    "## People and what was said",
)
"""The headings of the notes a resident writes for itself when its context is condensed."""
COMPACTION_REQUEST = (
    "Before you go on, write down for yourself what you will want to remember of all that has "
    "happened so far: from here on, these notes and the last few things that happened are all "
    "you will have of it. Write them out now, here in your reply, in your own words, under "
    "exactly these headings:\n\n"
    + "\n".join(NOTES_HEADINGS)
    + "\n\nYour reply is the notes themselves, written out in full, and nothing else."
)

SUMMARY = "These are my notes of what came before, as I wrote them down for myself.\n\n{summary}"
"""The notes in the context, introduced in the resident's own voice, so that it knows them for its
own, and finds there its earlier notes when it writes new ones."""
