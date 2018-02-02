#! /usr/local/bin/python2.7
# Copyright (C) 2014  Han Lin <hotdogee [at] gmail [dot] com>
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 3 of the License, or
# (at your option) any later version.

"""
Update the sequence id and coordinates of a GFF3 file using an alignment file generated by the fasta_diff program

Changelog:
1.1:
* If ##sequence-region is found in the old GFF3 file, generate and write an updated ##sequence-region to the new GFF3.
* Detect ##FASTA and ignore all following lines.
"""

__version__ = '1.1'

from collections import OrderedDict
from collections import defaultdict
import logging
logging.basicConfig(level=logging.DEBUG, format='%(levelname)-8s %(message)s')


class GffUpdater(object):
    """
    Initialize a GffUpdater instance with an alignment_file
    gff_updater = GffUpdater(alignment_file)
    Update a gff_file with the update method
    gff_updater.update(gff_file)
    """
    HEADER = 0
    KEEP = 1
    SEQUENCE_REMOVED = 2
    POSITION_REMOVED = 3
    SEQUENCE_REGION = 4

    def __init__(self, alignment_list_tsv_file, updated_postfix, removed_postfix):
        self.alignment_list = GffUpdater.read_alignment_list_tsv(alignment_list_tsv_file)
        # create a dictionary to lookup alignments using old_id as key
        self.alignment_dict = defaultdict(list)
        for a in self.alignment_list:
            self.alignment_dict[a[0]].append(a)
        self.updated_postfix = updated_postfix
        self.removed_postfix = removed_postfix

    def update(self, gff_file):
        """
        Updates the gff_file using the alignment_list_tsv_file
        :param str gff_file: The GFF3 file to be updated
        """
        logging.info('Processing GFF3 file: %s...', gff_file)
        self.gff_file = gff_file
        self.has_fasta = False
        self._find_root_features()
        self._update_features()
        self._output_features()

    @staticmethod
    def read_alignment_list_tsv(alignment_list_tsv_file):
        """
        Parse an alignment_list_tsv and returns a list
        :param alignment_list_tsv_file: The output alignment file of fasta_diff.py
        :type alignment_list_tsv_file: string or file
        :return: a list of [old_id, old_start, old_end, new_id, new_start, new_end]
        """
        tsv_format = [str, int, int, str, int, int]
        alignment_list_tsv_file_f = alignment_list_tsv_file
        if isinstance(alignment_list_tsv_file, str):
            logging.info('Reading alignment data from: %s...', alignment_list_tsv_file_f.name)
            alignment_list_tsv_file_f = open(alignment_list_tsv_file, 'rb')

        alignment_list = []
        for line in alignment_list_tsv_file_f:
            alignment_list.append([f(t) for f, t in zip(tsv_format, line.split('\t'))])

        if isinstance(alignment_list_tsv_file, str):
            alignment_list_tsv_file_f.close()
        else:
            logging.info('Reading alignment data from: %s...', alignment_list_tsv_file_f.name)
        logging.info('  Alignments: %d', len(alignment_list))

        return alignment_list

    def _find_root_features(self):
        """
        Parses the GFF3 parent child relationship tree and records the information in two variables:
        * gff_line_root_list: the root feature line number of each line
        * gff_root_line_dict: the children feature line numbers of each root line
        """
        import re
        self.gff_line_root_list = []
        self.gff_root_line_dict = defaultdict(list)
        gff_id_line = {}
        feature_count = 0
        with open(self.gff_file, 'rb') as gff_f:
            current_line_num = 0
            for line in gff_f:
                if len(line.strip()) == 0:
                    # ingore blank line
                    continue
                if line[0] == '#':
                    self.gff_line_root_list.append(current_line_num)
                    self.gff_root_line_dict[current_line_num].append(current_line_num)
                    if line.strip() == '##FASTA':
                        # This notation indicates that the annotation portion of the file is at an end and that the
                        # remainder of the file contains one or more sequences (nucleotide or protein) in FASTA format.
                        self.has_fasta = True
                        break
                else:
                    # parse id and parent
                    attributes = line.split('\t')[8]
                    attribute_dict = dict(re.findall('([^=;]+)=([^=;\n]+)', attributes))
                    if 'ID' in attribute_dict:
                        gff_id_line[attribute_dict['ID']] = current_line_num
                    if 'Parent' in attribute_dict:
                        self.gff_line_root_list.append(self.gff_line_root_list[gff_id_line[attribute_dict['Parent']]])
                        self.gff_root_line_dict[self.gff_line_root_list[gff_id_line[attribute_dict['Parent']]]].append(current_line_num)
                    else:
                        self.gff_line_root_list.append(current_line_num)
                        self.gff_root_line_dict[current_line_num].append(current_line_num)
                    feature_count += 1
                current_line_num += 1
        logging.info('  Total features: %d', feature_count)

    def _update_features(self):
        """
        Goes through the GFF3 file, updating the ids and coordinates of each feature and
        checks for removed ids and coordinates. When a feature is marked for removal, its root parent is looked up
        and all of the children are marked for removal as well
        Each feature is assigned one of three tags: KEEP, SEQUENCE_REMOVED, POSITION_REMOVED
        * gff_line_status_dict: contains the assigned tags for each line
        * gff_line_list: unmodified text for each line in the GFF3 file
        * gff_converted_line_dict: updated text for each un-removed line in the GFF3 file
        """
        self.gff_line_status_dict = {}
        self.gff_line_list = []
        self.gff_converted_line_dict = {}
        with open(self.gff_file, 'rb') as in_f:
            current_line_num = 0
            for line in in_f:
                if len(line.strip()) == 0:
                    # ingore blank line
                    continue
                if line[0] == '#':
                    line_strip = line.strip()
                    self.gff_converted_line_dict[current_line_num] = line
                    if line_strip.startswith('##sequence-region'):
                        self.gff_line_status_dict[current_line_num] = GffUpdater.SEQUENCE_REGION
                    elif line_strip == '##FASTA':
                        # This notation indicates that the annotation portion of the file is at an end and that the
                        # remainder of the file contains one or more sequences (nucleotide or protein) in FASTA format.
                        break
                    else:
                        self.gff_line_status_dict[current_line_num] = GffUpdater.HEADER
                elif current_line_num not in self.gff_line_status_dict or self.gff_line_status_dict[current_line_num] == GffUpdater.KEEP:
                    tokens = line.split('\t')
                    if tokens[0] in self.alignment_dict:
                        start, end = int(tokens[3]), int(tokens[4]) # positive 1-based integer coordinates
                        mappings = self.alignment_dict[tokens[0]]
                        start_mapping = filter(lambda m: m[1] < start and start <= m[2], mappings)
                        end_mapping = filter(lambda m: m[1] < end and end <= m[2], mappings)
                        # we got a bad annotation if start or end pos is N
                        if len(start_mapping) != 1 or len(end_mapping) != 1:
                            for lc in self.gff_root_line_dict[self.gff_line_root_list[current_line_num]]:
                                self.gff_line_status_dict[lc] = GffUpdater.POSITION_REMOVED
                        else:
                            tokens[0] = mappings[0][3]
                            tokens[3] = str(start - start_mapping[0][1] + start_mapping[0][4])
                            tokens[4] = str(end - end_mapping[0][1] + end_mapping[0][4])
                            self.gff_line_status_dict[current_line_num] = GffUpdater.KEEP
                            self.gff_converted_line_dict[current_line_num] = '\t'.join(tokens)
                    else:
                        for lc in self.gff_root_line_dict[self.gff_line_root_list[current_line_num]]:
                            self.gff_line_status_dict[lc] = GffUpdater.SEQUENCE_REMOVED
                self.gff_line_list.append(line)
                current_line_num += 1

    def _output_sequence_region(self):
    #def _output_sequence_region(self, updated_file_f):
        """
        Write new "##sequence-region seqid start end" lines to updated_file_f
        :param updated_file_f: write to this file object
        :return: None
        """
        from itertools import groupby
        from itertools import chain
        self.sequence_regions = dict()
        for new_id, alignments in groupby(sorted(self.alignment_list, key=lambda a: a[3]), key=lambda a: a[3]):
            pos = list(chain(*[(a[4], a[5]) for a in alignments]))
            # convert from 0-based to 1-based coordinate system
            #updated_file_f.write('##sequence-region %s %d %d\n' % (new_id, min(pos) + 1, max(pos)))
            self.sequence_regions[new_id] = '##sequence-region %s %d %d\n' % (new_id, min(pos) + 1, max(pos))

    def _output_features(self):
        """
        Write the updated and removed features into two separate files
        :param updated_postfix: The text to append to the GFF3 file holding the updated features
        :param removed_postfix: The text to append to the GFF3 file holding the removed features
        """
        from os.path import splitext
        gff_root, gff_ext = splitext(self.gff_file)
        updated_file = gff_root + self.updated_postfix + gff_ext
        removed_file = gff_root + self.removed_postfix + gff_ext
        updated_count = 0
        removed_count = 0
        #sequence_region_written = False
        wrote_sequence_region = set()
        self._output_sequence_region()
        with open(updated_file, 'wb') as updated_file_f, open(removed_file, 'wb') as removed_file_f:
            for lc, line in enumerate(self.gff_line_list):
                if self.gff_line_status_dict[lc] == GffUpdater.KEEP:
                    Scaffold = self.gff_converted_line_dict[lc].split("\t")[0]
                    if Scaffold not in wrote_sequence_region:
                        updated_file_f.write(self.sequence_regions[Scaffold])
                        wrote_sequence_region.add(Scaffold)
                    updated_file_f.write(self.gff_converted_line_dict[lc])
                    updated_count += 1
                elif self.gff_line_status_dict[lc] == GffUpdater.HEADER:
                    updated_file_f.write(self.gff_converted_line_dict[lc])
                #elif self.gff_line_status_dict[lc] == GffUpdater.SEQUENCE_REGION and not sequence_region_written:
                #    self._output_sequence_region(updated_file_f)
                #    sequence_region_written = True
                elif self.gff_line_status_dict[lc] == GffUpdater.POSITION_REMOVED or self.gff_line_status_dict[lc] == GffUpdater.SEQUENCE_REMOVED:
                    removed_file_f.write(line)
                    removed_count += 1
        logging.info('  Updated features: %d', updated_count)
        logging.info('  Removed features: %d', removed_count)


if __name__ == '__main__':
    import sys
    import argparse
    from textwrap import dedent
    parser = argparse.ArgumentParser(formatter_class=argparse.RawDescriptionHelpFormatter, description=dedent("""\
    Update the sequence id and coordinates of a GFF3 file using an alignment file generated by the fasta_diff.py program.
    Updated features are written to a new file with '_updated'(default) appended to the original GFF3 file name.
    Feature that can not be updated, due to the id being removed completely or the feature contains regions that
    are removed or replaced with Ns, are written to a new file with '_removed'(default) appended to the original GFF3 file name.

    Example:
        fasta_diff.py old.fa new.fa | %(prog)s a.gff b.gff c.gff
    """))
    parser.add_argument('gff_files', metavar='GFF_FILE', nargs='+', type=str, help='List one or more GFF3 files to be updated')
    parser.add_argument('-a', '--alignment_file', type=argparse.FileType('rb'), default=sys.stdin,
                        help='The alignment file generated by fasta_diff.py, a TSV file with 6 columns: old_id, old_start, old_end, new_id, new_start, new_end (default: STDIN)')
    parser.add_argument('-u', '--updated_postfix', default='_updated',
                        help='The filename postfix for updated features (default: "_updated")')
    parser.add_argument('-r', '--removed_postfix', default='_removed',
                        help='The filename postfix for removed features (default: "_removed")')
    parser.add_argument('-v', '--version', action='version', version='%(prog)s ' + __version__)

    test_lv = 0 # debug
    if test_lv == 1:
        REMOVED = 3
        EXTRA_NS = 2
        KEEP = 1
        from os.path import splitext
        from glob import glob
        try:
            import cPickle as pickle
        except:
            import pickle
        gff_files = glob('*.gff')
        for gff_file in gff_files:
            args = parser.parse_args(['alignment_list_pickle', gff_file])
            alignment_list = pickle.load(open(args.alignment_file, 'rb'))
            alignment_dict = defaultdict(list)
            for a in alignment_list:
                alignment_dict[a[0]].append(a)
            # types = REMOVED, EXTRA_NS, KEEP
            gff_line_root_list, gff_root_line_dict = gff_get_root(args.gff_file)
            gff_line_status_dict = {}
            gff_line_list = []
            gff_converted_line_dict = {}
            with open(args.gff_file, 'rb') as in_f:
                line_count = 0
                for line in in_f:
                    if line[0] == '#':
                        gff_line_status_dict[line_count] = KEEP
                        gff_converted_line_dict[line_count] = line
                    elif line_count not in gff_line_status_dict or gff_line_status_dict[line_count] == KEEP:
                        tokens = line.split('\t')
                        if tokens[0] in alignment_dict:
                            start, end = int(tokens[3]), int(tokens[4]) # positive 1-based integer coordinates
                            mappings = alignment_dict[tokens[0]]
                            start_mapping = filter(lambda m: m[1] < start and start <= m[2], mappings)
                            end_mapping = filter(lambda m: m[1] < end and end <= m[2], mappings)
                            # we got a bad annotation if start or end pos is N
                            if len(start_mapping) != 1 or len(end_mapping) != 1:
                                for lc in gff_root_line_dict[gff_line_root_list[line_count]]:
                                    gff_line_status_dict[lc] = EXTRA_NS
                            else:
                                tokens[0] = mappings[0][3]
                                tokens[3] = str(start - start_mapping[0][1] + start_mapping[0][4])
                                tokens[4] = str(end - end_mapping[0][1] + end_mapping[0][4])
                                gff_line_status_dict[line_count] = KEEP
                                gff_converted_line_dict[line_count] = '\t'.join(tokens)
                        else:
                            for lc in gff_root_line_dict[gff_line_root_list[line_count]]:
                                gff_line_status_dict[lc] = REMOVED
                    gff_line_list.append(line)
                    line_count += 1
            # write output files
            gff_root, gff_ext = splitext(args.gff_file)
            gff_out_filename = gff_root + '_ncbi' + gff_ext
            gff_removed_filename = gff_root + '_removed' + gff_ext
            gff_extra_Ns_filename = gff_root + '_extra_Ns' + gff_ext
            with open(gff_extra_Ns_filename, 'wb') as extra_Ns_f:
                with open(gff_removed_filename, 'wb') as removed_f:
                    with open(gff_out_filename, 'wb') as out_f:
                        for lc, line in enumerate(gff_line_list):
                            if gff_line_status_dict[lc] == KEEP:
                                out_f.write(gff_converted_line_dict[lc])
                            elif gff_line_status_dict[lc] == EXTRA_NS:
                                extra_Ns_f.write(line)
                            elif gff_line_status_dict[lc] == REMOVED:
                                removed_f.write(line)
    else:
        args = parser.parse_args()
        gff_updater = GffUpdater(args.alignment_file, args.updated_postfix, args.removed_postfix)
        for gff_file in args.gff_files:
            gff_updater.update(gff_file)
