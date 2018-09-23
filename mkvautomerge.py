#
# mkvautomerge - mkvmerge batch processing
# Copyright (C) 2016, 2017 Sergiu Deitsch <sergiu.deitsch@gmail.com>
#
# This file is part of mkvautomerge.
#
# Tracker is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# Tracker is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with Tracker.  If not, see <http://www.gnu.org/licenses/>.
#

from iso639 import languages
from itertools import chain
from pathlib import Path
import glob
import os
import re
import subprocess
import sys

def subtitle_language_code(filename):
    with open(filename, 'r') as f:
        for line in f:
            match = re.search('id: ([a-z]{2})', line)

            if match != None:
                try:
                    lang = languages.get(part1=match.group(1))
                    return lang.part2b
                except KeyError:
                    pass

    return None

def subtitle_forced(filename):
    with open(filename, 'r') as f:
        for line in f:
            match = re.search('forced subs: (ON|OFF)', line)

            if match != None:
                try:
                    lang = languages.get(part1=match.group(1))
                    return lang.part2b
                except KeyError:
                    pass

    return None

def mkvmerge_path():
    return os.path.expandvars('%PROGRAMFILES%\\MKVToolNix\\mkvmerge.exe')

def filename_language(p):
    stem = p.stem
    code = str(stem).rsplit('-', maxsplit=1)[-1]

    splitted = code.rsplit('.', maxsplit=1)
    lang = splitted[0]
    forced = splitted[-1] == 'forced'

    if not forced:
        forced = stem.casefold().rfind('forced') != -1

    try:
        languages.get(part2b=lang)

        return lang, forced
    except KeyError:
        return None, forced

def generate_default_output_filename(files):
    mkv_filenames = [filename for filename in files if filename.suffix == '.mkv']

    if mkv_filenames:
        template = Path(mkv_filenames[0].name)
        generated_output_filename = template.with_name(template.stem +
                '-merged' + template.suffix)

        return generated_output_filename

    return None

def files_to_trash(files):
    for glob_file in files:
        yield glob_file

        if glob_file.suffix == '.idx':
            # Remove the complementary .sub file
            sub_file = glob_file.with_suffix('.sub')

            if sub_file.exists():
                yield sub_file


class ProgressGenerator(object):
    def __init__(self, process):
        self.percent = 0
        self.new_percent = 0
        self.process = process
        self.out = process.stdout
        self.high = 100

        try:
            self.__next__()
            # HACK: Make sure we not not skip the first iteration while showing
            # the progress bar.
            self.percent = 0
            self.new_percent = 1
        except StopIteration:
            if self.error_message != None:
                raise IOError(self.error_message)
            else:
                raise IOError

    def __len__(self):
        return self.high

    def __iter__(self):
        return self

    def do_step(self):
        self.percent = self.percent + 1
        return self.percent

    def readline(self):
        data = b''
        result = b''

        while True:
            ch = self.out.read(1)

            if not ch:
                result = b''
                break

            data += ch

            if data.endswith(b'\r') or data.endswith(b'\n'):
                result = data[:-1]
                data = b''

                if result:
                    break

        return result

    def __next__(self):
        if self.percent < self.new_percent:
            return self.do_step()

        if not self.percent < self.high:
            raise StopIteration

        while True:
            line = self.readline()

            if not line:
                if self.percent < self.high:
                    self.percent = self.high

                    return self.percent
                else:
                    raise StopIteration

            # TODO decode properly
            match = re.search('Progress: (\\d+)%', line.decode())

            if match != None:
                self.new_percent = int(match.group(1))

                if self.percent < self.new_percent:
                    return self.do_step()
            else:
                match = re.search('^Error: (.*)$', line.decode(), flags=re.M)

                if match != None:
                    self.error_message = match.group(1)
                    raise StopIteration

        raise StopIteration

def show_progress(process):
    from tqdm import tqdm

    gen = ProgressGenerator(process)
    bar_format = '{l_bar}{bar}| {elapsed} ETA: {remaining}'

    for i in tqdm(gen, desc='mkvmerge', bar_format=bar_format):
        pass

if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser('mkvautomerge')
    parser.add_argument('input',
                        nargs='*', action='append',
                        help='input files to merge')
    parser.add_argument('-i', metavar='FILE', dest='input',
                        nargs='+', action='append',
                        help='input files to merge')
    parser.add_argument('-o', '--output', metavar='FILE',
                        nargs=1,
                        help='merged output file')
    parser.add_argument('-n', '--dry-run', action='store_true',
                        default=False,
                        help='dry run')
    parser.add_argument('-d', '--delete', action='store_true',
                        default=False,
                        help='move files used for merging to the trash')
    parser.add_argument('-I', '--include', metavar='PATTERN',
                        nargs='+',
                        help='include pattern for input directories')

    args = parser.parse_args()

    if args.dry_run:
        print('DRY RUN')

    all_glob_files = []

    currentdir = os.getcwd()
    dirs = [Path(currentdir)]

    # Expand globbing expressions first
    for filename in chain.from_iterable(args.input):
        glob_files = [Path(file) for file in glob.glob(filename)]

        for glob_file in glob_files:
            if glob_file.is_dir():
                dirs += [glob_file]
            else:
                all_glob_files += [glob_file]

    # Now filter directories
    for directory in dirs:
        for pattern in args.include:
            globbed_files = [entry.relative_to(currentdir) for entry in directory.glob(pattern)]
            all_glob_files += globbed_files

    if not all_glob_files:
        print('error: no files specified', file=sys.stderr)
        sys.exit(-1)

    merge_args = [mkvmerge_path()]

    if args.output != None:
        merge_args += ['-o', args.output]
    else:
        generated_output_filename = \
            generate_default_output_filename(all_glob_files)

        if generated_output_filename != None:
            # TODO make sure generated_output_filename does not exist
            # Use the first .mkv as template and append merged
            merge_args += ['-o', str(generated_output_filename)]
        else:
            # TODO cannot generate a default output filename
            pass

    for glob_filename in all_glob_files:
        print('including file', glob_filename)
        lang, forced = filename_language(glob_filename)

        if lang == None:
            if glob_filename.suffix == '.idx':
                lang = subtitle_language_code(str(glob_filename))

        if lang != None:
            merge_args += ['--language', '0:{}'.format(lang)]

        if forced:
            merge_args += ['--forced-track', '0:1']
            merge_args += ['--track-name', '0:Forced']

        merge_args += [str(glob_filename)]

    returncode = None

    try:
        if not args.dry_run:
            try:
                process = subprocess.Popen(merge_args, stdout=subprocess.PIPE,
                        bufsize=1)

                show_progress(process)

                while returncode is None:
                    returncode = process.poll()

                succeeded = returncode == 0
            except IOError as error:
                print('error: {}'.format(error), file=sys.stderr)
                succeeded = False
        else:
            succeeded = True

        if not succeeded:
            if returncode != None:
                print('error: mkvmerge failed with the exit code {}'.format(returncode),
                        file=sys.stderr)
            else:
                print('error: mkvmerge failed', file=sys.stderr)

        if not args.dry_run:
            from send2trash import send2trash
            trash_file = lambda file: send2trash(str(file))
        else:
            trash_file = lambda file: None

        if succeeded and args.delete:
            for glob_file in files_to_trash(all_glob_files):
                print('moving {} to trash'.format(str(glob_file)))

                trash_file(glob_file)

        if succeeded:
            print('completed.')
    except KeyboardInterrupt:
        sys.stdout.flush()
        print('\nprocessing aborted.')
        succeeded = False
