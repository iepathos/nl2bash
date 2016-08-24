"""
Simplified bash tokenizer and parser built using bashlex.
"""

# builtin
from __future__ import print_function

import re
import shlex
import sys
sys.path.append("../data")

from utils import ENGLISH_STOPWORDS, word2num

import bast, errors, tokenizer, bparser

from nltk.stem.wordnet import WordNetLemmatizer
lmtzr = WordNetLemmatizer()

DEBUG = False

# Regular expressions used to tokenize an English sentence.
# _WORD_SPLIT = re.compile(b"^\s+|\s*,\s*|\s+$|^[\(|\[|\{|\<|\'|\"|\`]|[\)|\]|\}|\>|\'|\"|\`]$")
_WORD_SPLIT = re.compile(b"^\s+|\s*,\s*|\s+$|^[\(|\[|\{|\<]|[\)|\]|\}|\>]$")
_WORD_SPLIT_RESPECT_QUOTES = re.compile(b'(?:[^\s,"]|"(?:\\.|[^"])*")+')
_DIGIT_RE = re.compile(br"\d+")

_NUM = b"_NUM"
_LONG_PATTERN = b"_LONG_PATTERN"

COMBINED_FLAG_AND_ARG = re.compile(r"^(\-\w)(\d+)$")

head_commands = [
    "find", "xargs",
    "grep", "egrep",
    "sed", "awk",
    "ls", "rm",
    "cp", "mv",
    "wc", "chmod",
    "tar", "sort",
    "head", "tail",
    "chown"
]

special_operators = [
    "|",
    "`",
    "<(",
    "(",
    ")>",
    ")",
    "$("
]

# pseudo command names appeared in the collected data
pseudo_head_commands = [
    "parallel",
    "replace",
    "mplayer",
    "process",
    "execute",
    "rmdir",
    "pdfgrep",
    "fastqc",
    "ffmpeg",
    "cmd2",
    "command1",
    "command2"
]

def reserved_words():
    with open("/home/xilin/Projects/helper/bashlex/bash_keywords.txt") as f:
        _words = f.readlines()
    return [w.strip() for w in _words]

reserved_words = reserved_words()
all_utilities = set(reserved_words[reserved_words.index("alias"):])

def is_option(word):
    return word.startswith('-')

def is_double_option(word):
    return word.startswith('--')

def is_english_word(word):
    """Check if a token is normal English word."""
    return bool(re.match('[A-Za-z\-\'\(\)]+$', word, re.IGNORECASE))

def is_headcommand(word):
    return word in all_utilities or word in pseudo_head_commands

def rw_signature(cmd):
    tokens = bash_tokenizer(cmd)
    if not tokens:
        return None
    for token in tokens:
        if token.startswith('-') or \
            token in reserved_words or \
            token in pseudo_head_commands or \
            token in special_operators:
            reserved_words.add(token)
    signature = ' '.join(list(reserved_words))
    return signature

def basic_tokenizer(sentence, lower_case=True, normalize_digits=True,
                    normalize_long_pattern=True,
                    lemmatization=True):
    """Very basic tokenizer: used for English tokenization."""
    sentence = sentence.replace('`\'', '"') \
            .replace('``', '"') \
            .replace("''", '"') \
            .replace(' \'', ' "') \
            .replace('\' ', '" ') \
            .replace('`', '"') \
            .replace('(', '( ') \
            .replace(')', ' )')
            # .replace('[', '[ ') \
            # .replace('{', '{ ') \
            # .replace(']', ' ]') \
            # .replace('}', ' }') \
            # .replace('<', '< ') \
            # .replace('>', ' >')
    sentence = re.sub('^\'', '"', sentence)
    sentence = re.sub('\'$', '"', sentence)

    sentence = re.sub('(,\s+)|(,$)', ' ', sentence)
    sentence = re.sub('(;\s+)|(;$)', ' ', sentence)
    sentence = re.sub('(:\s+)|(:$)', ' ', sentence)
    sentence = re.sub('(\.\s+)|(\.$)', ' ', sentence)

    sentence = re.sub('\'s', '\\\'s', sentence)
    sentence = re.sub('\'re', '\\\'re', sentence)
    sentence = re.sub('\'ve', '\\\'ve', sentence)
    sentence = re.sub('\'d', '\\\'d', sentence)
    sentence = re.sub('\'t', '\\\'t', sentence)

    words = re.findall(_WORD_SPLIT_RESPECT_QUOTES, sentence)

    normalized_words = []
    for i in xrange(len(words)):
        word = words[i].strip()

        # remove unnecessary upper cases
        if lower_case:
            if len(word) > 1 and word[0].isupper() and word[1:].islower():
                word = word.lower()

        # lemmatization
        if lemmatization:
            word = lmtzr.lemmatize(word)

        # remove English stopwords
        if word in ENGLISH_STOPWORDS:
            continue

        # covert number words into numbers
        if word in word2num:
            word = str(word2num[word])

        # normalize regular expressions
        if not is_english_word(word):
            # msg = word + ' -> '
            if not word.startswith('"'):
                word = '"' + word
            if not word.endswith('"'):
                word = word + '"'
            # msg += word
            # print(msg)

        # normalize long patterns
        if ' ' in word and len(word) > 3:
            try:
                assert(word.startswith('"') and word.endswith('"'))
            except AssertionError, e:
                print("Quotation Error: space inside word " + sentence)
            if normalize_long_pattern:
                word = _LONG_PATTERN

        # normalize digits
        word = re.sub(_DIGIT_RE, _NUM, word) if normalize_digits and not is_option(word) else word

        # convert possessive expression
        if word.endswith("'s"):
            normalized_words.append(word[:-2])
            normalized_words.append("'s")
        else:
            normalized_words.append(word)

    return normalized_words

def bash_tokenizer(cmd, normalize_digits=True, normalize_long_pattern=True,
                   recover_quotation=True):
    cmd = cmd.replace('\n', ' ').strip()
    tokens = []
    if not cmd:
        return tokens

    def normalize_word(node, norm_digit, norm_long_pattern, recover_quote):
        w = recover_quotation(node) if recover_quote else node.word
        if ' ' in w:
            try:
                assert(w.startswith('"') and w.endswith('"'))
            except AssertionError, e:
                print("Quotation Error: space inside word " + w)
            if norm_long_pattern:
                w = _LONG_PATTERN
        return re.sub(_DIGIT_RE, _NUM, w) if norm_digit and not is_option(w) else w

    def with_quotation(node):
        return (node.pos[1] - node.pos[0] - len(node.word)) == 2

    def recover_quotation(node):
        if with_quotation(node):
            return cmd[node.pos[0] : node.pos[1]]
        else:
            return node.word

    def parse(node, tokens):
        if not type(node) is bast.node:
            tokens.append(str(node))
            return
        if node.kind == "word":
            if node.parts:
                # commandsubstitution, processsubstitution, parameter
                if node.parts[0].kind == "processsubstitution":
                    if '>' in node.word:
                        tokens.append('>(')
                        for child in node.parts:
                            parse(child, tokens)
                        tokens.append(')')
                    elif '<' in node.word:
                        tokens.append('<(')
                        for child in node.parts:
                            parse(child, tokens)
                        tokens.append(')')
                elif node.parts[0].kind == "parameter" or \
                    node.parts[0].kind == "tilde":
                    w = node.word
                    word = normalize_word(node, normalize_digits, normalize_long_pattern,
                                          recover_quotation)
                    tokens.append(word)
                else:
                    for child in node.parts:
                        parse(child, tokens)
            else:
                w = node.word
                word = normalize_word(node, normalize_digits, normalize_long_pattern,
                                      recover_quotation)
                tokens.append(word)
        elif node.kind == "pipe":
            w = node.pipe
            tokens.append(w)
        elif node.kind == "list":
            if len(node.parts) > 2:
                # multiple commands, not supported
                tokens.append(None)
            else:
                parse(node.parts[0], tokens)    # ignoring the ';' operator
        elif node.kind == "commandsubstitution":
            tokens.append('`')
            parse(node.command, tokens)
            tokens.append('`')
        elif node.kind == "processsubstitution":
            parse(node.command, tokens)
        elif node.kind == "parameter":
            # not supported
            tokens.append(None)
        elif hasattr(node, 'parts'):
            for child in node.parts:
                parse(child, tokens)
        elif node.kind == "operator":
            # not supported
            tokens.append(None)
        elif node.kind == "redirect":
            # not supported
            tokens.append(None)
            # if node.type == '>':
            #     parse(node.input, tokens)
            #     tokens.append('>')
            #     parse(node.output, tokens)
            # elif node.type == '<':
            #     parse(node.output, tokens)
            #     tokens.append('<')
            #     parse(node.input, tokens)
        elif node.kind == "for":
            # not supported
            tokens.append(None)
        elif node.kind == "if":
            # not supported
            tokens.append(None)
        elif node.kind == "while":
            # not supported
            tokens.append(None)
        elif node.kind == "until":
            # not supported
            tokens.append(None)
        elif node.kind == "assignment":
            # not supported
            tokens.append(None)
        elif node.kind == "function":
            # not supported
            tokens.append(None)
        elif node.kind == "tilde":
            # not supported
            tokens.append(None)
        elif node.kind == "heredoc":
            # not supported
            tokens.append(None)

    try:
        bash_ast = bparser.parse(cmd)
    except tokenizer.MatchedPairError, e:
        print("Cannot parse: %s - MatchedPairError" % cmd.encode('utf-8'))
        # return basic_tokenizer(cmd, normalize_digits, False)
        return None
    except errors.ParsingError, e:
        print("Cannot parse: %s - ParsingError" % cmd.encode('utf-8'))
        # return basic_tokenizer(cmd, normalize_digits, False)
        return None
    except NotImplementedError, e:
        print("Cannot parse: %s - NotImplementedError" % cmd.encode('utf-8'))
        # return basic_tokenizer(cmd, normalize_digits, False)
        return None
    except IndexError, e:
        print("Cannot parse: %s - IndexError" % cmd.encode('utf-8'))
        # empty command
        return None
    except AttributeError, e:
        print("Cannot parse: %s - AttributeError" % cmd.encode('utf-8'))
        # not a bash command
        return None

    for node in bash_ast:
        parse(node, tokens)
        if None in tokens:
            print("Unsupported: %s" % cmd.encode('utf-8'))
            return None

    return [token.encode('utf-8') for token in tokens]

def basic_tokenizer_regex(sentence, normalize_digits=True, lower_case=True):
    """Very basic tokenizer: used for English tokenization."""
    words = []
    for space_separated_fragment in sentence.replace('\n', ' ').strip().split():
        words.extend(re.split(_WORD_SPLIT, space_separated_fragment))
    normalized_words = []
    for i in xrange(len(words)):
        w = words[i].strip()
        word = re.sub(_DIGIT_RE, _NUM, w) if normalize_digits and not is_option(w) else w
        if lower_case:
            # remove unnecessary upper cases
            if len(word) > 1 and word[0].isupper() and word[1:].islower():
                word = word.lower()
        normalized_words.append(word.encode('utf-8'))
    return normalized_words

# -- Outdated ---

def split_flags(cmd, word):

    if cmd == "tar" and all(c in "xtcrujzvf" for c in word):
        for c in word:
            yield "-" + c
    elif cmd != "find":
        if word.startswith("--"):

            for flag in word.split('='):
                yield flag

        elif word.startswith("-"):

            # turn -n1 into -n, 1
            match = COMBINED_FLAG_AND_ARG.match(word)
            if match:
                yield match.group(1)
                yield match.group(2)

            # turns -xyz into -x, -y, -z
            else:
                for flag in word[1:]:
                    yield "-" + flag
        else:
            yield word
    else:
        yield word


def test_split_flags(cmd, flag, expected):
    print(" --> testing flag splitting on {} {}... ".format(cmd, flag), end="")
    result = list(split_flags(cmd, flag))
    if result == expected:
        print("ok {}".format(result))
    else:
        print("got {}".format(result))
        assert result == expected # False

def parse(code):
    """
    Yields all simple bash commands found in the code, e.g. ["ls", "-l"]
    """
    try:
        parts = parse(code)
    except Exception as e:
        if DEBUG: print("warning: failed to parse {} ({}: {})".format(repr(code), type(e), e), file=sys.stderr)
        return

    if DEBUG: print("parsed: {}".format(repr(code)), file=sys.stderr)

    for ast in parts:

        class Visitor(ast.nodevisitor):
            def __init__(self):
                self.simplecmds = []
            def visitcommand(self, cmd, parts):
                if parts[0].kind == "word":
                    cmd = parts[0].word
                    args = []
                    for part in parts[1:]:
                        if part.kind == "word":
                            if cmd in ["xargs", "time", "nohup", "nice"] and \
                               part.word in ["find", "mv", "cp", "tar", "rm"]:
                                self.simplecmds.append([cmd] + args)
                                args = []
                                cmd = part.word
                            else:
                                args += list(split_flags(cmd, part.word))
                    self.simplecmds.append([cmd] + args)

        v = Visitor()
        v.visit(ast)
        for cmd in v.simplecmds:
            yield cmd


if __name__ == "__main__":
    # This lets you call `python bash.py "cmd"` to test the parser
    DEBUG = True
    test_split_flags("ls", "-lsh", ["-l", "-s", "-h"])
    test_split_flags("tar", "--exclude=something", ["--exclude", "something"])
    test_split_flags("tar", "czvf", ["-c", "-z", "-v", "-f"])
    test_split_flags("find", "-iname", ["-iname"])
    test_split_flags("xargs", "-n1", ["-n", "1"])
    test_split_flags("nice", "-n20", ["-n", "20"])
    for cmd in parse(" ".join(sys.argv[1:])):
        print(cmd)
