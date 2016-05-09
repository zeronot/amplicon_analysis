#!/usr/bin/env python

import argparse
import os
import time
import logging as log
import pandas as pd
import matplotlib
matplotlib.use('Agg')  # non-interactive backend
import matplotlib.pyplot as plt
import seaborn as sns
import numpy as np
from string import Template
from subprocess import Popen, PIPE

_DEF_COV_THRESHOLD = 100
_DATA_FOLDER = 'data'
_SAMPLE_DATA = 'SampleData.csv'
_SAMPLE_SELECTION = 'SampleSelection.csv'
_ALIGNMENT_FOLDER = 'Alignment'
_COV_FOLDER = 'covs'
_PLOT_FOLDER = 'plots'
_REPORT_FOLDER = 'reports'
_BED_FOLDER = 'beds'
_MERGED_COV_FILE = 'all_samples.perbase.cov'

# Required BEDtools v.2.19.0 or above!
_BEDTOOLS_COVPERBASE_CMD = ('coverageBed -d -a $bed -b $bam' +
                            ' | grep -v \'^all\' > $out')


def _setup_argparse():
    """It prepares the command line argument parsing"""

    desc = 'description'
    formatter_class = argparse.ArgumentDefaultsHelpFormatter
    parser = argparse.ArgumentParser(description=desc,
                                     formatter_class=formatter_class)
    parser.add_argument('-p', '--project', dest='project_fpath', required=True,
                        help='Project folder')
    parser.add_argument('-v', '--verbose', dest='verbosity',
                        help='increase output verbosity', action='store_true')
    parser.add_argument('-t', '--cov_threshold', dest='cov_threshold',
                        help='Coverage threshold', default=_DEF_COV_THRESHOLD,
                        type=int)

    args = parser.parse_args()
    return args


def _get_options():
    """It checks arguments values"""
    args = _setup_argparse()

    # Setting up logging system
    if args.verbosity:
        log.basicConfig(format="[%(levelname)s] %(message)s", level=log.DEBUG)
    else:
        log.basicConfig(format="[%(levelname)s] %(message)s", level=log.ERROR)

    # Checking if input file is provided
    project_absfpath = os.path.abspath(args.project_fpath)
    if not os.path.isdir(project_absfpath):
        raise IOError('Project folder does not exist. Check path.')
    else:
        args.project_fpath = project_absfpath

        # Checking if input file is provided
        data_fpath = os.path.join(project_absfpath, _DATA_FOLDER)
        args.sample_data_fpath = os.path.join(data_fpath, _SAMPLE_DATA)
        args.sample_selec_fpath = os.path.join(data_fpath, _SAMPLE_SELECTION)
        if not os.path.isfile(args.sample_data_fpath):
            raise IOError('SampleData file does not exist in "' +
                          data_fpath + '"')
        if not os.path.isfile(args.sample_selec_fpath):
            raise IOError('SampleSelection file does not exist in "' +
                          data_fpath + '"')

    # Checking if coverage threshold is a positive integer
    if (not isinstance(args.cov_threshold, int)) or args.cov_threshold < 0:
        raise IOError('Coverage threshold must be a positive integer')

    return args


def _get_time(fancy=True):
    """Timestamp"""
    if fancy:
        return time.strftime("%Y-%m-%d %H:%M:%S")
    else:
        return time.strftime("%Y-%m-%d_%H-%M-%S")


def parse_cov_file(fpath, sep='\t'):
    """It reads a TSV file into a pandas dataframe
    :param fpath: TSV file path
    :param sep: field delimiter character
    """
    header = ['ref', 'start', 'end', 'feature', 'base', 'coverage', 'sample']
    df = pd.read_csv(fpath, sep=sep, header=None)

    # Checking that header and dataframe columns coincide in number
    try:
        assert (len(header) == len(df.columns))
    except AssertionError:
        log.error('File "' + fpath + '" has an incorrect number of columns')

    df.columns = header

    return df


def cov_plot(df, out_folder, cov_threshold=None, feats=None, samps=None):
    """It plots the coverage per base for each sample for a specific reference
    :param df: input dataframe
    :param out_folder: output folder to store the plots
    :param cov_threshold: coverage threshold
    :param feats: list of features to plot
    :param samps: list of samples to plot
    """

    if not feats:
        features = list(set(df['feature']))
    else:
        features = feats

    for feature in features:
        df_feature = df[df['feature'] == feature]

        if not samps:
            samples = list(set(df_feature['sample']))
        else:
            samples = samps

        sns.set_style("darkgrid")

        # Plotting a line for each sample
        for sample in samples:
            sample_data = df_feature[df_feature['sample'] == sample]
            plt.plot(sample_data['base'], sample_data['coverage'],
                     color='black', alpha=0.5)

            # Setting plot limits
            plt.ylim(0, df_feature['coverage'].max() + 50)
            plt.xlim(0, df_feature['base'].max() + 1)

            # Plotting coverage threshold
            if cov_threshold:
                plt.hlines(y=cov_threshold, xmin=plt.xlim()[0],
                           xmax=plt.xlim()[1], color='r')

            # Customizing labels
            plt.title(feature)
            plt.xlabel('Position (bp)')
            plt.ylabel('Coverage')

            # Saving plot and clearing it
            figname = sample + '-' + feature + '.pbcov.png'
            plt.savefig(os.path.join(out_folder, figname))
            plt.close()


def percentage(part, whole):
    """It computes percentages
    :param part: part of the data
    :param whole: total data
    """
    # Avoiding ZeroDivision error and returning negative number if so
    if whole > 0:
        return round(100 * float(part) / float(whole), 2)
    else:
        return -1


def _get_cov_stats(df, out_fpath, cov_threshold=None):
    """Writes an excel file with some stats for each sample and feature"""

    # Summarizing data
    # http://bconnelly.net/2013/10/summarizing-data-in-python-with-pandas/
    df_cov = df.get(['sample', 'feature', 'coverage'])
    df_grouped = df_cov.groupby(['sample', 'feature'])
    stats = df_grouped.agg([np.min, np.max]).reset_index()
    stats.columns = ['sample', 'feature', 'min', 'max']

    # If there is coverage threshold, add coverage breadth
    if cov_threshold:
        col_name = '%cov_breadth_' + str(cov_threshold) + 'x'
        stats[col_name] = df_grouped.agg([lambda x: percentage(
                                np.size(np.where(x > cov_threshold)),
                                np.size(x))
                              ]).reset_index().iloc[:, -1].values

    # Writing to excel
    # http://xlsxwriter.readthedocs.org/working_with_pandas.html
    writer = pd.ExcelWriter(os.path.join(out_fpath, 'stats.xlsx'),
                            engine='xlsxwriter')
    stats.to_excel(writer, sheet_name='stats', index=False)

    # If there is coverage threshold, add conditional formatting
    if cov_threshold:
        workbook = writer.book
        worksheet = writer.sheets['stats']

        # Defining formats
        green_format = workbook.add_format({'bg_color': '#C6EFCE'})
        red_format = workbook.add_format({'bg_color': '#FFC7CE'})
        orange_format = workbook.add_format({'bg_color': '#FFD27F'})

        # Applying formats to cell range
        cell_range = 'E2:E' + str(len(stats.index) + 1)
        worksheet.conditional_format(cell_range, {'type': 'cell',
                                                  'criteria': 'equal to',
                                                  'value': 100,
                                                  'format': green_format})
        worksheet.conditional_format(cell_range, {'type': 'cell',
                                                  'criteria': 'equal to',
                                                  'value': 0,
                                                  'format': red_format})
        worksheet.conditional_format(cell_range, {'type': 'cell',
                                                  'criteria': 'between',
                                                  'minimum': 0,
                                                  'maximum': 100,
                                                  'format': orange_format})

    writer.save()


def create_folder(folder):
    """Creates a new folder given a name and a parent directory
    :param folder: path of the folder
    """
    if os.path.exists(folder):
        log.warning('Folder "' + folder + '" already exists')
    else:
        try:
            os.makedirs(folder)
            log.debug('Creating folder "' + folder + '"')
        except:
            raise IOError('Unable to create output folders. Check permissions')


def run_bedtools_get_cov(inds, bam_path, bed_path, cov_path, cmd):
    """Runs a bedtools getCoverage command
    :param inds: names of the samples
    :param bam_path: path of the input BAM file
    :param bed_path: path of the input BED file
    :param cov_path: path of the output coverage file
    :param cmd: template of the command
    """
    template = Template(cmd)
    for ind in inds:
        bam = os.path.join(bam_path, ind + '.bam')
        bed = os.path.join(bed_path, ind + '.bed')
        out = os.path.join(cov_path, ind + '.pbcov')
        cmd = template.substitute(bam=bam, bed=bed, out=out)
        p = Popen(cmd, shell=True, stdout=PIPE, stderr=PIPE)
        output = p.communicate()[1]
        if p.returncode != 0:
            raise RuntimeError('Failed BEDtools command "' + cmd + '". ' +
                               output)


def concatenate_files(files, out_fpath):
    """It concatenates multiple files into one file
    :param files: paths of the input files
    :param out_fpath: path of the output file
    """
    out_fhand = open(out_fpath, 'w')

    for f in files:
        in_fhand = open(f, 'r')
        fname = os.path.splitext(os.path.basename(f))[0]
        for line in in_fhand:
            line = line.strip() + '\t' + fname + '\n'
            out_fhand.write(line)
        in_fhand.close()

    out_fhand.flush()
    out_fhand.close()


def main():
    """The main function"""

    # Parsing options
    options = _get_options()
    if options.verbosity:
        log.info('START "' + _get_time() + '"')
        log.debug('Options parsed: "' + str(options) + '"')

    # Setting up output folder paths
    bam_folder = os.path.join(options.project_fpath, _ALIGNMENT_FOLDER)
    bed_folder = os.path.join(options.project_fpath, _BED_FOLDER)
    cov_folder = os.path.join(options.project_fpath, _COV_FOLDER)
    plot_folder = os.path.join(options.project_fpath, _PLOT_FOLDER)
    report_folder = os.path.join(options.project_fpath, _REPORT_FOLDER)

    # Creating output folders
    log.info('Creating output folders...')
    create_folder(bam_folder)
    create_folder(bed_folder)
    create_folder(cov_folder)
    create_folder(plot_folder)
    create_folder(report_folder)

    # Retrieving desired sample names
    sample_selec_fhand = open(options.sample_selec_fpath, 'r')
    samples = [sample.strip() for sample in sample_selec_fhand]
    log.debug('Samples specified: "' + str(samples) + '"')

    # Checking if there is a BAM file for each specified sample
    # Also creating a ordered BAM file list depending on samples list order
    bam_files = [f for f in os.listdir(bam_folder) if f.endswith('.bam')]
    log.debug('BAM files found: "' + str(bam_files) + '"')
    samples_with_bam = []
    bam_ordered = []
    for sample in samples:
        for bam in bam_files:
            if bam.startswith(sample):
                samples_with_bam.append(sample)
                bam_ordered.append(bam)
                break
    samples_without_bam = list(set(samples) - set(samples_with_bam))
    if len(samples_without_bam) != 0:
        raise ValueError('No BAM file for samples: "' +
                         str(samples_without_bam) + '"')

    # Creating a BED file for each desired sample
    sample_data_df = pd.read_csv(options.sample_data_fpath, sep='\t', header=0)
    desired_columns = ['chromosome', 'amplicon_start', 'amplicon_end',
                       'amplicon_name']
    for i, sample in enumerate(samples):
        subselect = sample_data_df[desired_columns][(sample_data_df.sample_ID ==
                                                     sample)]
        bed_fname = os.path.splitext(bam_ordered[i])[0] + '.bed'
        bed_fpath = os.path.join(bed_folder, bed_fname)

        if os.path.isfile(bed_fpath):
            log.warning('File "' + bed_fpath + '" already exists. Overwriting')

        subselect.to_csv(bed_fpath, sep='\t', index=False, header=False)

    # Running BEDtools
    log.info('Running BEDtools...')
    inds = map(lambda x: os.path.splitext(x)[0], bam_ordered)
    run_bedtools_get_cov(inds, bam_folder, bed_folder, cov_folder,
                         _BEDTOOLS_COVPERBASE_CMD)

    # Merging cov files
    log.info('Merging individual coverage files...')
    cov_files = [f for f in os.listdir(cov_folder) if f.endswith('.pbcov')]
    log.debug('Coverage files found: "' + str(cov_files) + '"')
    cov_abspath = map(lambda x: os.path.join(cov_folder, x), cov_files)
    concatenate_files(cov_abspath, os.path.join(cov_folder, _MERGED_COV_FILE))

    # Parsing input file
    log.info('Reading coverage file...')
    df = parse_cov_file(os.path.join(cov_folder, _MERGED_COV_FILE))

    # Plotting
    log.info('Generating coverage plots...')
    cov_plot(df, plot_folder, options.cov_threshold)

    # Creating excel with statistics
    _get_cov_stats(df, report_folder, options.cov_threshold)

    if options.verbosity:
        log.info('END "' + _get_time() + '"')


if __name__ == '__main__':
    main()
