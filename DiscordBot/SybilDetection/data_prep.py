import argparse
import random

def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument('--graph_file', type=str, required=True)
    parser.add_argument('--gt_file', type=str, required=True)
    parser.add_argument('--out_file', type=str, required=True)
    parser.add_argument('--n_attack', type=int, required=True)
    args = parser.parse_args()
    return args


def main(args):
    pos_idx = 4038
    edges = []
    with open(args.graph_file, 'r') as f:
        for line in map(lambda x: x.split(), f.readlines()):
            node1, node2 = int(line[0]), int(line[1])
            if (node1 <= 4038 and node2 <= 4038) or (node1 > 4038 and node2 > 4038):
                edges.append((node1, node2))

    attack_edges = set()
    while len(attack_edges) < 2 * args.n_attack:
        pos_nodes = random.choices(list(range(1, 4039)), k=args.n_attack)
        neg_nodes = random.choices(list(range(4039, 8078)), k=args.n_attack)
        for node1, node2 in zip(pos_nodes, neg_nodes):
            attack_edges.add((node1, node2))
            attack_edges.add((node2, node1))
        if len(attack_edges) >= args.n_attack:
            break

    edges += list(attack_edges)

    with open(args.out_file, 'w') as f:
        for node1, node2 in edges[:-1]:
            f.write(f"{node1} {node2}\n")
        node1, node2 = edges[-1]
        f.write(f"{node1} {node2}")

if __name__ == "__main__":
    args = parse_args()
    main(args)