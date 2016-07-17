"""
Custom VCF parser for generating a site frequency spectrum data file for consumption by dadi

"""
import logging
from collections import defaultdict
import pprint

# VCF column headers
CHROM = 0
POS = 1
ID = 2
REF = 3
ALT = 4
QUAL = 5
FILTER = 6
INFO = 7
FORMAT = 8
GENOTYPE = 9

def extract_variant_sites(population, samples, variants):

    with open('./vcf/' + population + '.vcf', 'r') as infile:

        # get the first line
        header = infile.readline()

        # skip over the block comments, stop when we reach the column header
        while header.startswith("##"):
            header = infile.readline()

        # get the column headers
        columns = header.split()

        for line in infile:

            # convert string to list
            locus = line.split()

            # index by chromosome and position
            site = (locus[CHROM], locus[POS])

            # skip low quality sites
            if locus[QUAL] != '.' and float(locus[QUAL]) < 30:
                logging.debug('{}\t{}\tLowQual\t{}'.format(population, site, locus[QUAL]))
                continue

            # get the reference allele
            ref = locus[REF]

            # get the alternatve allele, deal with the stupid <NON_REF> notation used by BP_RESOLUTION
            alt_list = locus[ALT].split(',').remove('<NON_REF>')

            # skip polyallelic sites
            if len(alt_list) > 1:
                logging.debug('{}\t{}\tPolyAllelic\t{}/{}'.format(population, site, ref, alt_list))
                continue

            # resolve empty list issue
            alt = ref if not alt_list else alt[0]

            # skip indels
            if len(ref) > 1 or len(alt) > 1:
                logging.debug('{}\t{}\tInDel\t{}/{}'.format(population, site, ref, alt))
                continue

            if site not in variants:
                # initialise site locus dictionary
                variants[site] = dict()

            # initialise
            for allele in [ref, alt]:
                if allele not in variants[site]:
                    variants[site][allele] = defaultdict(int)

            # get the indices for the genotype column (e.g. GT:AD:DP:GQ:PL:SB)
            format = locus[FORMAT].split(':')

            GT = format.index('GT')
            DP = format.index('DP')
            GQ = format.index('GQ')

            # populate the variant dictionary
            for sample in samples:

                # get the genotype for the sample
                genotype = locus[columns.index(sample)].split(':')

                # skip low coverage samples
                if int(genotype[DP]) < 5:
                    logging.debug('{}\t{}\tLowCoverage\t{}\t{}'.format(population, site, sample, genotype[DP]))
                    continue

                # skip low quality samples
                if int(genotype[GQ]) < 30:
                    logging.debug('{}\t{}\tLowCoverage\t{}\t{}'.format(population, site, sample, genotype[DP]))
                    continue

                # count the observed alleles
                if genotype[GT] == '0/0':
                    # homozygous reference
                    variants[site][ref][population] += 2

                elif genotype[GT] == '0/1':
                    # heterozygous
                    variants[site][ref][population] += 1
                    variants[site][alt][population] += 1

                elif genotype[GT] == '1/1':
                    # homozygous alternate
                    variants[site][alt][population] += 2

def generate_frequency_spectrum(populations):
    """
    Generates the site frequency spectrum for a given set of samples

    :param populations: Dictionary of populations
    :return:
    """

    # create a dictionary of variant sites
    variants = dict()

    # parse each of the populations and extract the variant sites
    for pop in populations:
        extract_variant_sites(pop, populations[pop], variants)

    # TODO skip het sites in outgroup
    # TODO skip hom sites
    # TODO skip sites with < 5 sample coverage

    pp = pprint.PrettyPrinter(depth=6)
    pp.pprint(variants)

if __name__ == '__main__':
    # TODO remove when done testing
    # population, accession codes
    POPULATIONS = dict()

    # Wild mountain hare / Lepus timidus
    POPULATIONS['OUT'] = ['SRR824842']

    # # Domestic breeds
    POPULATIONS['DOM'] = ['SRR997325', 'SRR997320'] #, 'SRR997321', 'SRR997327', 'SRR997323', 'SRR997326', 'SRR997324', 'SRR997322']
    #
    # # Wild French
    # POPULATIONS['WLD-FRE'] = ['SRR997319', 'SRR997317', 'SRR997304', 'SRR997303', 'SRR997318', 'SRR997316', 'SRR997305']
    #
    # # Wild Iberian / Oryctolagus cuniculus algirus
    # POPULATIONS['WLD-IB1'] = ['SRR827758', 'SRR827761', 'SRR827762', 'SRR827763', 'SRR827764', 'SRR827765']
    #
    # # Wild Iberian / Oryctolagus cuniculus cuniculus
    # POPULATIONS['WLD-IB2'] = ['SRR827759', 'SRR827760', 'SRR827766', 'SRR827767', 'SRR827768', 'SRR827769']

    print generate_frequency_spectrum(POPULATIONS)
