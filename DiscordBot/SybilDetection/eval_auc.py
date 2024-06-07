import argparse

from sklearn.metrics import roc_auc_score


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument('--pred_file', type=str, required=True)
    parser.add_argument('--gt_file', type=str, required=True)
    args = parser.parse_args()
    return args


def main(args):
    pred = {}
    gt = {}
    with open(args.pred_file, 'r') as f:
        for line in map(lambda x: x.split(), f.readlines()):
            idx, score = int(line[0]), float(line[1])
            pred[idx] = score
    with open(args.gt_file, 'r') as f:
        pos_nodes = list(map(int, f.readline().strip().split()))
        for idx in pos_nodes:
            gt[idx] = 1
        neg_nodes = list(map(int, f.readline().strip().split()))
        for idx in neg_nodes:
            gt[idx] = 0

    pred_arr = []
    gt_arr = []
    for key in pred.keys():
        if key in gt:
            pred_arr.append(pred[key])
            gt_arr.append(gt[key])

    print(roc_auc_score(gt_arr, pred_arr))
    


if __name__ == "__main__":
    args = parse_args()
    main(args)