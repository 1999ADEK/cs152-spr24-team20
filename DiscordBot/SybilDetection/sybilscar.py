import argparse
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
import math
import random
from typing import Optional
from tqdm import tqdm


import numpy as np


class SybilScar:
    def __init__(
            self,
            theta_pos: float = 0.6,
            theta_neg: float = 0.4,
            theta_unl: float = 0.5,
            weight: float = 0.6,
            max_iter: int = 10,
            network_file: Optional[str] = None,
            train_file: Optional[str] = None,
        ):
        self.theta_pos = theta_pos
        self.theta_neg = theta_neg
        self.theta_unl = theta_unl
        self.weight = weight
        self.max_iter = max_iter

        self.network_map = defaultdict(list)
        if network_file:
            self.read_network(network_file)
        self.prior = np.zeros(self.num_nodes)
        self.posterior = np.zeros(self.num_nodes)
        if train_file:
            self.set_prior(train_file)


    def read_network(self, network_file: str):
        with open(network_file, 'r') as f:
            for line in tqdm(f):
                node1, node2 = map(int, line.strip().split())
                assert node1 != node2
                self.network_map[node1].append((node2, self.weight - 0.5))
        self.posterior = np.zeros(self.num_nodes)
        self.posterior_pre = np.zeros(self.num_nodes)
        self.prior = np.zeros(self.num_nodes)


    @property
    def num_nodes(self):
        return len(self.network_map)
    

    def set_prior(self, train_file: str):
        with open(train_file, 'r') as f:
            pos_train_nodes = list(map(int, f.readline().strip().split()))
            for node in pos_train_nodes:
                self.prior[node] = self.theta_pos - 0.5
            neg_train_nodes = list(map(int, f.readline().strip().split()))
            for node in neg_train_nodes:
                self.prior[node] = self.theta_neg - 0.5


    def write_posterior(self, out_file: str):
        with open(out_file, 'w') as f:
            for i in range(self.num_nodes):
                f.write(f"{i} {self.posterior[i] + 0.5:.10f}\n")


    def lbp_thread(self, start, end):
        for index in range(start, end):
            node = self.ordering_array[index]
            self.posterior[node] = sum(2 * self.posterior_pre[nei[0]] * nei[1] for nei in self.network_map[node])
            self.posterior[node] += self.prior[node]
            self.posterior[node] = min(0.5, max(-0.5, self.posterior[node]))

    def lbp(self, num_threads: int = 1):
        if math.log(self.num_nodes) < self.max_iter:
            self.max_iter = int(math.log(self.num_nodes))
        
        self.ordering_array = np.arange(self.num_nodes)
        np.copyto(self.posterior, self.prior)

        for _ in tqdm(range(self.max_iter)):
            np.copyto(self.posterior_pre, self.posterior)
            random.shuffle(self.ordering_array)

            n = math.ceil(self.num_nodes / num_threads)
            with ThreadPoolExecutor(max_workers=num_threads) as executor:
                futures = []
                for i in range(num_threads):
                    start = i * n
                    end = min((i + 1) * n, self.num_nodes)
                    futures.append(executor.submit(self.lbp_thread, start, end))
                for future in futures:
                    future.result()


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument('--network_file', type=str, required=True)
    parser.add_argument('--train_file', type=str, required=True)
    parser.add_argument('--out_file', type=str, required=True)
    parser.add_argument('--max_iter', type=int, default=10)
    parser.add_argument('--theta_pos', type=float, default=0.6)
    parser.add_argument('--theta_neg', type=float, default=0.4)
    parser.add_argument('--theta_unl', type=float, default=0.5)
    parser.add_argument('--weight', type=float, default=0.6)
    parser.add_argument('--num_threads', type=int, default=1)
    args = parser.parse_args()
    return args


def main(args):
    random.seed(152)

    solver = SybilScar(
        theta_pos=args.theta_pos,
        theta_neg=args.theta_neg,
        theta_unl=args.theta_unl,
        weight=args.weight,
        max_iter=args.max_iter,
        network_file=args.network_file,
        train_file=args.train_file,
    )
    solver.lbp(num_threads=args.num_threads)
    solver.write_posterior(args.out_file)


if __name__ == "__main__":
    args = parse_args()
    main(args)