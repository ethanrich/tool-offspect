from pathlib import Path
from typing import Union, List
from offspect.cache.file import CacheFile, merge
import argparse
from ast import literal_eval
from .tms import cli_tms

try:
    from offspect.gui.__main__ import main as cli_gui
except ImportError:

    def cli_gui(*args, **kwargs):
        print("GUI was not found")


def cli_peek(args: argparse.Namespace):
    print(CacheFile(args.fname))


def cli_merge(args: argparse.Namespace):
    tf = merge(to=args.to, sources=args.sources)
    if args.verbose:
        print("Content of target file is now:")
        print(CacheFile(tf))


def get_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="offspect",
        description="Create, manipulate and inspect cachefiles for offline inspection of evoked potentials",
    )
    subparsers = parser.add_subparsers(dest="sub")

    # PEEK --------------------------------------------------------------------
    peek = subparsers.add_parser(
        name="peek", help="peek into a cachefile and print essential information"
    )
    peek.add_argument("fname", help="filename to peek into", type=str)

    # MERGE -------------------------------------------------------------------
    merge = subparsers.add_parser(name="merge", help="merge two cachefiles into one")
    merge.add_argument(
        "-t",
        "--to",
        help="filename to merge into. May not already exist",
        type=str,
        required=True,
        dest="to",
    )
    merge.add_argument(
        "-f",
        "--from",
        nargs="+",
        help="<Required> list of files to merge",
        required=True,
        dest="sources",
    )
    merge.add_argument("-verbose", "-v", help="be more verbose", action="store_true")

    # TMS ---------------------------------------------------------------------
    tms = subparsers.add_parser(
        name="tms", help="prepare cachefiles for a tms protocol"
    )
    tms.add_argument(
        "-t",
        "--to",
        help="filename of the cachefile to be populated",
        type=str,
        required=True,
        dest="to",
    )
    tms.add_argument(
        "-f",
        "--from",
        nargs="+",
        help="<Required> list of input files",
        required=True,
        dest="sources",
    )
    tms.add_argument(
        "-r",
        "--readout",
        type=str,
        help="the desired readout",
        required=True,
        dest="readout",
    )
    tms.add_argument(
        "-c",
        "--channel",
        type=str,
        help="the desired channel",
        required=True,
        dest="channel",
    )
    tms.add_argument(
        "-pp",
        "--prepost",
        nargs="+",
        help="<Required> positional arguments of pre and post duration",
        required=True,
        dest="prepost",
    )
    tms.add_argument(
        "-e",
        "--events",
        nargs="+",
        help="<Required> select event",
        required=False,
        type=str,
        dest="select_events",
    )
    # GUI ---------------------------------------------------------------------
    gui = subparsers.add_parser(name="gui", help="start the visual inspection GUI")
    gui.add_argument(
        "-r",
        "--resolution",
        help="Which resolution to use for the window. leave empty for default, or set to LR or HR",
        required=False,
        default="",
        dest="resolution",
    )
    gui.add_argument(
        "-f",
        "--file",
        help="Which file to load during startup",
        required=False,
        default=None,
        dest="filename",
    )

    # ------------------------------------------------------------------------
    return parser


def main():
    # get the parser
    parser = get_parser()
    # parse and run respective subcommands
    args, _ = parser.parse_known_args()
    if args.sub == "peek":
        cli_peek(args)
    elif args.sub == "merge":
        cli_merge(args)
    elif args.sub == "tms":
        cli_tms(args)
    elif args.sub == "gui":
        cli_gui(args)
    else:
        print("No valid subcommand specified")


# ----------------------------------------------------------------------------

from typing import Iterator


def format_help(parser) -> Iterator[str]:  # pragma no cover
    cb = ".. code-block:: none\n\n"

    title = parser.prog + "\n" + "~" * len(parser.prog)
    helpstr = parser.format_help()
    yield title + "\n"
    yield cb
    for line in helpstr.splitlines():
        yield "   " + line + "\n"
    yield "\n\n"
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            for choice, subparser in action.choices.items():
                title = subparser.prog + "\n" + "~" * len(subparser.prog)
                yield title + "\n"
                yield cb
                for line in subparser.format_help().splitlines():
                    yield "   " + line + "\n"
                yield "\n\n"


def create_cli_rst(fname: str):  # pragma no cover
    desc = """
   
offspect offers a command line interface. This interface can be accessed after installation of the package from the terminal, e.g. peek into a CacheFile with 

.. code-block:: bash

   offspect peek example.hdf5

"""
    helpstr = format_help(get_parser())
    with open(fname, "w") as f:
        f.write("Command Line Interface\n")
        f.write("----------------------\n")
        f.write(desc)
        for h in helpstr:
            f.write(h)
