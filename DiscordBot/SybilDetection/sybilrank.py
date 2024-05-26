import argparse
from collections import defaultdict
import math
from typing import Optional
from tqdm import tqdm


import numpy as np
from scipy.sparse import csr_matrix


class SybilRank:
    def __init__(
            self,
            alpha: float = 0.0,
            max_iter: int = 10,
            network_file: Optional[str] = None,
            train_file: Optional[str] = None,
        ):
        self.network_map = defaultdict(list)
        if network_file:
            self.read_network(network_file)
        self.prior = np.zeros(self.num_nodes)
        self.posterior = np.zeros(self.num_nodes)
        if train_file:
            self.set_prior(train_file)
        self.trans_mat = self.get_trans_mat()

        self.alpha = alpha
        self.max_iter = max_iter


    def read_network(self, network_file: str):
        with open(network_file, 'r') as f:
            for line in tqdm(f):
                node1, node2 = map(int, line.strip().split())
                assert node1 != node2
                self.network_map[node1].append(node2)
        self.posterior = np.zeros(self.num_nodes)
        self.prior = np.zeros(self.num_nodes)


    @property
    def num_nodes(self):
        return len(self.network_map)


    def set_prior(self, train_file: str):
        with open(train_file, 'r') as f:
            pos_train_nodes = list(map(int, f.readline().strip().split()))
            for node in pos_train_nodes:
                self.prior[node] = 1.0


    def get_trans_mat(self):
        num_entry = sum(len(neighbors) for neighbors in self.network_map.values())
        row_ind = np.zeros(num_entry, dtype=np.int64)
        col_ind = np.zeros(num_entry, dtype=np.int64)
        data = np.zeros(num_entry)
        k = 0
        for cur_row, neighbors in self.network_map.items():
            for neighbor in neighbors:
                row_ind[k] = cur_row
                col_ind[k] = neighbor
                data[k] = 1.0 / len(self.network_map[neighbor])
                k += 1
        return csr_matrix((data, (row_ind, col_ind)), shape=(self.num_nodes, self.num_nodes))
    

    def compute_posterior(self):
        self.power_iteration()
        self.normalize_posterior()


    def power_iteration(self):
        x = np.zeros(self.num_nodes)
        np.copyto(self.posterior, self.prior)
        if math.log(self.num_nodes) > self.max_iter:
            self.max_iter = int(math.log(self.num_nodes))

        for i in tqdm(range(self.max_iter)):
            x = self.trans_mat.dot(self.posterior)
            self.posterior = (1 - self.alpha) * x + self.alpha * self.prior


    def normalize_posterior(self):
        for i in range(self.num_nodes):
            self.posterior[i] /= len(self.network_map[i])


    def write_posterior(self, out_file: str):
        with open(out_file, 'w') as f:
            for i in range(self.num_nodes):
                f.write(f"{i} {self.posterior[i]:.10f}\n")


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument('--network_file', type=str, required=True)
    parser.add_argument('--train_file', type=str, required=True)
    parser.add_argument('--out_file', type=str, required=True)
    parser.add_argument('--max_iter', type=int, default=10)
    parser.add_argument('--alpha', type=float, default=0.0)
    args = parser.parse_args()
    return args


def main(args):
    solver = SybilRank(
        alpha=args.alpha,
        max_iter=args.max_iter,
        network_file=args.network_file,
        train_file=args.train_file,
    )
    solver.compute_posterior()
    solver.write_posterior(args.out_file)


if __name__ == "__main__":
    args = parse_args()
    main(args)