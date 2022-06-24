import argparse
import time
import dendropy
import numpy as np

from qr.adr_theory import *
from qr.fitness_cost import cost
from qr.quintet_sampling import *
from qr.utils import *


def main(args):
    st_time = time.time()
    script_path = os.path.realpath(__file__).rsplit("/", 1)[0]

    # input args
    species_tree_path = args.speciestree
    gene_tree_path = args.genetrees
    output_path = args.outputtree
    sampling_method = args.samplingmethod.lower()
    random.seed(args.seed)
    cost_func = args.cost.lower()
    header = """*********************************
*     Quintet Rooting v1.1      *
*********************************"""
    print(header)

    # reading gene tree and unrooted species tree topology files
    tns = dendropy.TaxonNamespace()
    unrooted_species = dendropy.Tree.get(path=species_tree_path, schema='newick',
                                         taxon_namespace=tns, rooting="force-unrooted", suppress_edge_lengths=True)
    if len(tns) < 5:
        raise Exception("Species tree " + species_tree_path + " has less than 5 taxa!\n")
    gene_trees = dendropy.TreeList.get(path=gene_tree_path, schema='newick', taxon_namespace=tns,
                                       rooting="force-unrooted", suppress_edge_lengths=True)

    # reading fixed quintet topology files
    tns_base = dendropy.TaxonNamespace()
    unrooted_quintets_base = dendropy.TreeList.get(path=script_path + '/qr/topologies/quintets.tre',
                                                   taxon_namespace=tns_base, schema='newick')
    rooted_quintets_base = dendropy.TreeList(taxon_namespace=tns_base)
    rooted_quintets_base.read(path=script_path + '/qr/topologies/caterpillar.tre', schema='newick',
                              rooting="default-rooted")
    rooted_quintets_base.read(path=script_path + '/qr/topologies/pseudo_caterpillar.tre', schema='newick',
                              rooting="default-rooted")
    rooted_quintets_base.read(path=script_path + '/qr/topologies/balanced.tre', schema='newick',
                              rooting="default-rooted")
    rooted_quintet_indices = np.load(script_path + '/qr/rooted_quintet_indices.npy')

    print('Loading time: %.2f sec' % (time.time() - st_time))
    ss_time = time.time()

    # search space of rooted trees
    rooted_candidates = get_all_rooted_trees(unrooted_species)
    r_score = np.zeros(len(rooted_candidates))

    print('Creating search space time: %.2f sec' % (time.time() - ss_time))
    sm_time = time.time()

    # set of sampled quintets
    taxon_set = [t.label for t in tns]
    sample_quintet_taxa = []
    if len(taxon_set) == 5 or sampling_method == 'd':
        sample_quintet_taxa = list(itertools.combinations(taxon_set, 5))
    elif sampling_method == 'tc':
        sample_quintet_taxa = triplet_cover_sample(taxon_set)
    elif sampling_method == 'le':
        sample_quintet_taxa = linear_quintet_encoding_sample(unrooted_species, taxon_set)
    elif sampling_method == 'rl':
        sample_quintet_taxa = random_linear_sample(taxon_set)

    print('Quintet sampling time: %.2f sec' % (time.time() - sm_time))
    proc_time = time.time()

    print("Number of taxa (n):", len(tns))
    print("Size of search space (|R|):", len(rooted_candidates))
    print("Size of sampled quintets set (|Q*|):", len(sample_quintet_taxa))

    # preprocessing
    quintet_scores = np.zeros((len(sample_quintet_taxa), 7))
    quintet_unrooted_indices = np.zeros(len(sample_quintet_taxa), dtype=int)
    quintets_r_all = []

    for j in range(len(sample_quintet_taxa)):
        q_taxa = sample_quintet_taxa[j]
        quintets_u = [
            dendropy.Tree.get(data=map_taxon_namespace(str(q), q_taxa) + ';', schema='newick', rooting='force-unrooted',
                              taxon_namespace=tns) for q in unrooted_quintets_base]
        quintets_r = [
            dendropy.Tree.get(data=map_taxon_namespace(str(q), q_taxa) + ';', schema='newick', rooting='force-rooted',
                              taxon_namespace=tns) for q in rooted_quintets_base]
        subtree_u = unrooted_species.extract_tree_with_taxa_labels(labels=q_taxa, suppress_unifurcations=True)
        quintet_tree_dist = gene_tree_distribution(gene_trees, q_taxa, quintets_u)
        quintet_unrooted_indices[j] = get_quintet_unrooted_index(subtree_u, quintets_u)
        quintet_scores[j] = compute_cost_rooted_quintets(quintet_tree_dist, quintet_unrooted_indices[j],
                                                         rooted_quintet_indices, cost_func)
        quintets_r_all.append(quintets_r)

    print('Preprocessing time: %.2f sec' % (time.time() - proc_time))
    sc_time = time.time()

    # computing scores
    for i in range(len(rooted_candidates)):
        r = rooted_candidates[i]
        for j in range(len(sample_quintet_taxa)):
            q_taxa = sample_quintet_taxa[j]
            subtree_r = r.extract_tree_with_taxa_labels(labels=q_taxa, suppress_unifurcations=True)
            r_idx = get_quintet_rooted_index(subtree_r, quintets_r_all[j], quintet_unrooted_indices[j])
            r_score[i] += quintet_scores[j][r_idx]

    min_idx = np.argmin(r_score)
    with open(output_path, 'w') as fp:
        fp.write(str(rooted_candidates[min_idx]) + ';\n')

    print('Scoring time: %.2f sec' % (time.time() - sc_time))
    print('Scores of all rooted trees:\n', r_score)
    print('Best rooting:\n', rooted_candidates[min_idx])

    # computing confidence scores
    if args.confidencescore:
        confidence_scores = (np.max(r_score) - r_score) / np.sum(np.max(r_score) - r_score)
        tree_ranking_indices = np.argsort(r_score)
        with open(output_path + ".rank.cfn", 'w') as fp:
            for i in tree_ranking_indices:
                fp.write(str(rooted_candidates[i]) + ';\n')
                fp.write(str(confidence_scores[i]) + '\n')

    print('Total execution time: %.2f sec\n' % (time.time() - st_time))


def compute_cost_rooted_quintets(u_distribution, u_idx, rooted_quintet_indices, cost_func):
    """
    Scores the 7 possible rootings of an unrooted quintet
    :param np.ndarray u_distribution: unrooted quintet tree probability distribution
    :param int u_idx: index of unrooted binary tree
    :param np.ndarray rooted_quintet_indices: indices of partial orders for all rooted quintet trees
    :param str cost_func: type of the fitness function
    :rtype: np.ndarray
    """
    rooted_tree_indices = u2r_mapping[u_idx]
    costs = np.zeros(7)
    for i in range(7):
        idx = rooted_tree_indices[i]
        unlabeled_topology = idx_2_unlabeled_topology(idx)
        indices = rooted_quintet_indices[idx]
        costs[i] = cost(u_distribution, indices, unlabeled_topology, cost_func)
    return costs


def get_all_rooted_trees(unrooted_tree):
    """
    Generates all the possible rooted trees with a given unrooted topology
    :param dendropy.Tree unrooted_tree: an unrooted tree topology
    :rtype: list
    """
    rooted_candidates = []
    tree = dendropy.Tree(unrooted_tree)
    for edge in tree.preorder_edge_iter():
        try:
            tree.reroot_at_edge(edge, update_bipartitions=True)
            rooted_candidates.append(dendropy.Tree(tree))
        except:
            continue
    # removing duplicates
    for i in range(1, len(rooted_candidates)):
        if dendropy.calculate.treecompare.symmetric_difference(rooted_candidates[0], rooted_candidates[i]) == 0:
            rooted_candidates.pop(i)
            break
    return rooted_candidates


def parse_args():
    parser = argparse.ArgumentParser(description='== Quintet Rooting v1.1 ==')

    parser.add_argument("-t", "--speciestree", type=str,
                        help="input unrooted species tree in newick format",
                        required=True, default=None)

    parser.add_argument("-g", "--genetrees", type=str,
                        help="input gene trees in newick format",
                        required=True, default=None)

    parser.add_argument("-o", "--outputtree", type=str,
                        help="output file containing a rooted species tree",
                        required=True, default=None)

    parser.add_argument("-sm", "--samplingmethod", type=str,
                        help="quintet sampling method (TC for triplet cover, LE for linear encoding, RL for random "
                             "linear)", required=False, default='d')

    parser.add_argument("-cfs", "--confidencescore", action='store_true',
                        help="output confidence scores for each possible rooted tree as well as a ranking")

    parser.add_argument("-c", "--cost", type=str,
                        help="cost function (INQ for inequalities only)",
                        required=False, default='d')

    parser.add_argument("-rs", "--seed", type=int,
                        help="random seed", required=False, default=1234)

    args = parser.parse_args()
    return args


if __name__ == "__main__":
    main(parse_args())
