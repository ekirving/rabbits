import luigi
import multiprocessing
import os
import subprocess

# import the custom vcf parser
from vcfparser import *

# Based on example pipeline from http://coderscrowd.com/app/public/codes/view/229

# the reference genome
GENOME = "OryCun2.0"
GENOME_URL = "ftp://ftp.ensembl.org/pub/release-84/fasta/oryctolagus_cuniculus/dna/Oryctolagus_cuniculus.OryCun2.0.dna.toplevel.fa.gz"

# file containing the list of sequence capture regions, format <chr>:<start>-<stop>
INTERVAL_LIST = './targets.interval_list'

# population, accession codes
POPULATIONS = dict()

# Wild mountain hare / Lepus timidus
POPULATIONS['OUT'] = ['SRR824842']

# Domestic breeds
POPULATIONS['DOM'] = ['SRR997325','SRR997320','SRR997321','SRR997327','SRR997323','SRR997326','SRR997324','SRR997322']

# Wild French
POPULATIONS['WLD-FRE'] = ['SRR997319','SRR997317','SRR997304','SRR997303','SRR997318','SRR997316','SRR997305']

# Wild Iberian / Oryctolagus cuniculus algirus
POPULATIONS['WLD-IB1'] = ['SRR827758', 'SRR827761', 'SRR827762', 'SRR827763', 'SRR827764', 'SRR827765']

# Wild Iberian / Oryctolagus cuniculus cuniculus
POPULATIONS['WLD-IB2'] = ['SRR827759', 'SRR827760', 'SRR827766', 'SRR827767', 'SRR827768', 'SRR827769']

# the samtools flag for BAM file comression
DEFAULT_COMPRESSION = 6

# TODO find out how many workers there are
# no single worker should use more than 50% of the available cores
MAX_CPU_CORES = int(multiprocessing.cpu_count() * 0.5)

#  TODO java flags for best performance
# JAVA_FLAGS = '-Xmx8G -Xms8G'

def run_cmd(cmd):
    """
    Executes the given command in a system subprocess

    :param cmd: The system command to run (list|string)
    :return: The stdout stream
    """

    # subprocess only accepts strings
    cmd = [str(args) for args in cmd]

    # TODO write all bash commands to a script and log it
    print cmd

    # run the command
    proc = subprocess.Popen(cmd,
                            shell=False,
                            stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE)

    # fetch the output and error
    (stdout, stderr) = proc.communicate()

    # TODO remove when done debugging
    print vars(proc)

    # bail if something went wrong
    if proc.returncode:
        print stderr
        exit()

    return stdout

def unzip_file(gzip):
    """
    Unzip a gzipped file, using multi-threading when available

    :param gzip: The path to the gzip file
    :return: The uncompressed data stream
    """
    try:
        # use unpigz for multithreaded unzipping (if installed)
        return run_cmd(["unpigz",
                        "-c",                # output to stdout
                        "-p", MAX_CPU_CORES, # use the maximum cores
                        gzip])               # gzip file

    except OSError as e:
        # if it's not installed
        if e.errno == os.errno.ENOENT:

            # use single-threaded gunzip
            return run_cmd(["gunzip",
                            "-c",            # output to stdout
                            gzip])           # gzip file
        else:
            # escalate the exception
            raise e


class Curl_Download(luigi.Task):
    """
    Downloads a remote url to a local file path using cURL
    """
    url = luigi.Parameter()
    file = luigi.Parameter()

    def output(self):
        return luigi.LocalTarget(self.file)

    def run(self):
        # download the file
        stdout = run_cmd(["curl",
                          "-s",       # download silently
                          self.url])  # from this url

        # save the file
        with self.output().open('w') as fout:
            fout.write(stdout)

        print "====== cURL Downloading file ======"


class Sample_PairedEnd_Fastq(luigi.Task):
    """
    Fetches the two paired-end FASTQ files for a given sample ID
    """
    sample = luigi.Parameter()

    def output(self):
        return [luigi.LocalTarget("fastq/" + self.sample + "_1.fastq.gz"),
                luigi.LocalTarget("fastq/" + self.sample + "_2.fastq.gz")]

    def run(self):

        # NCBI SRA toolkit
        run_cmd(["fastq-dump",
                 "--gzip",              # outpute gzipped files
                 "--split-files",       # split paired end files
                 "--outdir", "./fastq", # output directory
                 self.sample])

        print "====== Downloaded Paired-end FASTQ ======"

class Reference_Genome_Fasta(luigi.Task):
    """
    Fetches the reference genome
    """
    genome = luigi.Parameter()
    # url = luigi.Parameter()

    def requires(self):
        global GENOME_URL
        # download the gzipped fasta file of the reference genome
        return Curl_Download(GENOME_URL, "fasta/" + self.genome + ".fa.gz")

    def output(self):
        return luigi.LocalTarget("fasta/" + self.genome + ".fa")

    def run(self):
        # unzip the file
        fasta = unzip_file(self.requires().file)

        with self.output().open('w') as fout:
            fout.write(fasta)

        print "====== Downloaded genome FASTA ======"

class Samtools_Faidx(luigi.Task):
    """
    Create the samtools fasta index for the reference genome, needed for GATK
    """
    genome = luigi.Parameter()

    def requires(self):
        return Reference_Genome_Fasta(self.genome)

    def output(self):
        return luigi.LocalTarget("fasta/" + self.genome + ".fa.fai")

    def run(self):
        run_cmd(["samtools1.3",
                 "faidx",                     # index needed for CRAM files
                 "fasta/" + self.genome + ".fa"]) # input file

        print "====== Built the samtools FASTA index ======"

class Picard_CreateSequenceDictionary(luigi.Task):
    """
    Create the sequence dictionary for the reference genome, needed for GATK
    """
    genome = luigi.Parameter()

    def requires(self):
        return Reference_Genome_Fasta(self.genome)

    def output(self):
        return luigi.LocalTarget("fasta/" + self.genome + ".fa")

    def run(self):
        run_cmd(["java", "-jar",
                 "/usr/local/picard-tools-2.5.0/picard.jar",
                 "CreateSequenceDictionary",
                 "R=fasta/" + self.genome + ".fa",        # reference fasta file
                 "O=fasta/" + self.genome + ".dict"])     # dictionary file

        print "====== Built the picard sequence dictionary ======"

class Bwa_Index_Bwtsw(luigi.Task):
    """
    Builds the BWA index for the reference genome, needed for performing alignments
    """
    genome = luigi.Parameter()

    def requires(self):
        return Reference_Genome_Fasta(self.genome)

    def output(self):
        extensions = ['amb', 'ann', 'bwt', 'pac', 'sa']
        return [luigi.LocalTarget("fasta/" + self.genome + ".fa." + ext) for ext in extensions]

    def run(self):
        run_cmd(["bwa",
                 "index",                         # index needed for bwa alignment
                 "-a", "bwtsw",                   # algorithm suitable for mammals
                 "fasta/" + self.genome + ".fa"]) # input file

        print "====== Built the BWA index ======"

class Bwa_Mem(luigi.Task):
    """
    Align the fastq files to the reference genome
    """
    sample = luigi.Parameter()
    genome = luigi.Parameter()

    def requires(self):
        return [Sample_PairedEnd_Fastq(self.sample),
                Bwa_Index_Bwtsw(self.genome)]

    def output(self):
        return luigi.LocalTarget("sam/" + self.sample + ".sam")

    def run(self):
        readgroup= "@RG\\tID:{sample}\\tSM:{sample}".format(sample=self.sample)

        # perform the alignment
        sam = run_cmd(["bwa",
                       "mem",                                   # align using the mem algorithm
                       "-t", MAX_CPU_CORES,                     # number of cores
                       "-R", readgroup,                         # readgroup metadata
                       "fasta/" + self.genome + ".fa",          # reference genome
                       "fastq/" + self.sample + "_1.fastq.gz",  # pair 1
                       "fastq/" + self.sample + "_2.fastq.gz"]) # pair 2

        # save the SAM file
        with self.output().open('w') as fout:
            fout.write(sam)

        print "====== Aligned the FASTQ using BWA ======"

class Samtools_Sort_Bam(luigi.Task):
    """
    Convert an uncompressed SAM file into BAM format, and sort it
    """
    sample = luigi.Parameter()
    genome = luigi.Parameter()

    def requires(self):
        return Bwa_Mem(self.sample, self.genome)

    def output(self):
        return luigi.LocalTarget("bam/" + self.sample + ".bam")

    def run(self):
        # perform the SAM -> BAM conversion and sorting
        bam = run_cmd(["samtools1.3",
                       "sort",                         # sort the reads
                       "-l", DEFAULT_COMPRESSION,      # level of compression
                       "-@", MAX_CPU_CORES,            # number of cores
                       "-O", "bam",                    # output a BAM file
                       "sam/" + self.sample + ".sam"]) # input a SAM file

        # save the BAM file
        with self.output().open('w') as fout:
            fout.write(bam)

        print "===== Converted SAM file to BAM ======"

class Picard_MarkDuplicates(luigi.Task):
    """
    Remove PCR duplicates, so we don't overestimate coverage
    """
    sample = luigi.Parameter()
    genome = luigi.Parameter()

    def requires(self):
        return Samtools_Sort_Bam(self.sample, self.genome)

    def output(self):
        return luigi.LocalTarget("bam/" + self.sample + ".rmdup.bam")

    def run(self):

        # https://broadinstitute.github.io/picard/command-line-overview.html#FixMateInformation
        run_cmd(["java", "-jar",
                 "/usr/local/picard-tools-2.5.0/picard.jar",
                 "FixMateInformation",
                 "INPUT=bam/" + self.sample + ".bam"])

        # https://broadinstitute.github.io/picard/command-line-overview.html#MarkDuplicates
        run_cmd(["java", "-jar",
                 "/usr/local/picard-tools-2.5.0/picard.jar",
                 "MarkDuplicates",
                 "INPUT=bam/" + self.sample + ".bam",
                 "OUTPUT=bam/" + self.sample + ".rmdup.bam",
                 "METRICS_FILE=bam/" + self.sample + ".rmdup.txt",
                 "REMOVE_DUPLICATES=true",
                 "QUIET=true"])

        print "==== Removed Duplicates from BAM ===="

class Samtools_Index_Bam(luigi.Task):
    """
    Create an index for the BAM file, for fast random access
    """
    sample = luigi.Parameter()
    genome = luigi.Parameter()

    def output(self):
        return luigi.LocalTarget("bam/" + self.sample + ".rmdup.bam.bai")

    def requires(self):
        return Picard_MarkDuplicates(self.sample, self.genome)

    def run(self):
        run_cmd(["samtools1.3",
                 "index",
                 "-b",  # create a BAI index
                 "bam/" + self.sample + ".rmdup.bam"])  # file to index

        print "==== Indexing CRAM ===="

class GATK_Variant_Call(luigi.Task):
    """
    Convert the BAM file into a BCF
    """
    population = luigi.Parameter()
    samples = luigi.ListParameter()
    genome = luigi.Parameter()
    intervallist = luigi.Parameter()

    def requires(self):
        # reference genome must be properly indexed
        yield Samtools_Faidx(self.genome)
        yield Picard_CreateSequenceDictionary(self.genome)

        # samples must be pre-processed
        for sample in self.samples:
            yield Samtools_Index_Bam(sample, self.genome)

    def output(self):
        return luigi.LocalTarget("vcf/" + self.population + ".vcf")

    def run(self):

        # make the list of input files
        bamfiles = sum([["-I", "bam/" + sample + ".rmdup.bam"] for sample in self.samples], [])

        run_cmd(["java", "-jar",
                 "../GenomeAnalysisTK.jar",
                 "-T", "HaplotypeCaller",                # use the HaplotypeCaller to call variants
                 "-R", "fasta/" + self.genome + ".fa",   # the indexed reference genome
                 "--genotyping_mode", "DISCOVERY",       # variant discovery
                 "--emitRefConfidence", "BP_RESOLUTION", # reference model emitted site by site
                 "--output_mode", "EMIT_ALL_SITES",  # produces calls at any callable site regardless of confidence
                 "-L", self.intervallist,                # limit to the given list of regions, <chr>:<start>-<stop>
                 "-stand_emit_conf", "10",               # min confidence threshold
                 "-stand_call_conf", "30",               # min call threshold
                 "-o", "vcf/" + self.population + ".vcf"]
                + bamfiles)

        print "===== Converted BAM file to BCF ======="


class Site_Frequency_Spectrum(luigi.Task):
    """
    Produce the site frequency spectrum, based on genotype calls from GATK HaplotypeCaller
    """
    populations = luigi.DictParameter()
    genome = luigi.Parameter()
    intervallist = luigi.Parameter()

    def requires(self):
        for pop in self.populations:
            yield GATK_Variant_Call(pop, self.populations[pop], self.genome, self.intervallist)

    def output(self):
        return luigi.LocalTarget("fsdata/" + self.genome + ".data")

    def run(self):

        # log everything to file
        logging.basicConfig(filename="fsdata/" + self.genome + ".log", level=logging.DEBUG)

        # generate the frequency spectrum
        fsdata = generate_frequency_spectrum(self.populations)

        # save the fsdata file
        with self.output().open('w') as fout:
            fout.write(fsdata)

        print "===== Generated the site frequency spectrum  ======="

class Custom_Genome_Pipeline(luigi.Task):
    """
    Run all the samples through the pipeline
    """

    def requires(self):
        return Site_Frequency_Spectrum(POPULATIONS, GENOME, INTERVAL_LIST)

if __name__=='__main__':
    luigi.run()