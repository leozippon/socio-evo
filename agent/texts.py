"""Every fixed text the runtime puts before a resident, kept together for the wording guard.

Templates take their fields with `str.format`. The tool descriptions of the runtime's own tools
live with their specs in `agent.files` and `agent.runtime`.
"""

GUIDE = """\
## How you act

You act through your tools, and only through them: what you write without calling a tool is \
for yourself alone, and no one hears it. Whenever something happens, you are told the time, \
where you are and which tools you can use at that moment; a tool that does not apply at the moment \
says so when you call it.

When you have nothing more to do for now, reply without calling a tool, and you will wait until \
something happens: someone speaks to you, something changes around you, or time passes. If \
someone speaks to you while you are thinking, you hear it at once.

A very long result is shortened in the middle. When your conversation grows long, it is \
condensed into a summary in your own words, and your last few exchanges are kept as they were; \
you can condense it yourself at any time with compact."""

FILES = """\
## Your files

These files are yours and stay with you from day to day; no other resident can read them. Read \
one with read_file when you need it, change it with write_file or edit_file, and see what you \
have with list_files. Paths are written like memory/people.md. The first line of each file in \
skills/ says what it is for."""

SKILLS_READ_ONLY = "You can read the files in skills/ but not change them."

KNOWN_FILES = {
    "background.md": "who you are",
    "memory/town.md": "what you know of the town and how it works",
    "memory/people.md": "the people you know",
    "memory/work.md": "your work",
}
"""What the files every resident has are for, as the index of files says."""

# Refusals and results of the file tools.
OUTSIDE = (
    "{path} is not one of your files; yours are background.md and those in memory/ and skills/."
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
NEEDS = "{tool} needs {argument} as {kind}."
TEXT = "text"
NUMBER = "a whole number from 1"

# What the runtime itself answers.
UNKNOWN_TOOL = "There is no tool called {name}."
UNREADABLE = "The arguments of this call could not be read, so nothing was done."
FAILED = "This could not be carried out."
NOT_CARRIED_OUT = "Not carried out: something came up first."
CONDENSING = "Condensing your conversation now."
CUT_OFF = "Your reply above ran past its length limit and was cut off there."
SHORTENED = "[... {count} characters left out here ...]"

# Compaction.
COMPACTION_REQUEST = """\
Your conversation is about to be condensed: from now on you will have only a summary of it and \
your last few exchanges. Write that summary now, in your own words, under exactly these headings:

## What I am doing and where I stand
## Facts I must not lose
## Decisions and their reasons
## Open questions
## People and what was said

Reply with the summary alone, without calling a tool."""

SUMMARY = "What came before, as you summarized it:\n\n{summary}"
