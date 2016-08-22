import argparse
import json
import os
import itertools
from collections import Counter

import numpy as np
from tqdm import tqdm
import nltk

from nltk_utils import set_span, tree_contains_span, find_max_f1_span

NULL = "-NULL-"
UNK = "-UNK-"


def bool_(arg):
    if arg == 'True':
        return True
    elif arg == 'False':
        return False
    raise Exception()


def get_args():
    parser = argparse.ArgumentParser()
    home = os.path.expanduser("~")
    source_dir = os.path.join(home, "data", "squad")
    target_dir = "data/squad"
    glove_dir = os.path.join(home, "data", "glove")
    parser.add_argument("--source_dir", default=source_dir)
    parser.add_argument("--target_dir", default=target_dir)
    parser.add_argument("--min_word_count", default=100, type=int)
    parser.add_argument("--min_char_count", default=500, type=int)
    parser.add_argument("--debug", default=False, type=bool_)
    parser.add_argument("--train_ratio", default=0.9, type=int)
    parser.add_argument("--glove_corpus", default="6B")
    parser.add_argument("--glove_dir", default=glove_dir)
    parser.add_argument("--glove_word_size", default=100, type=int)
    # TODO : put more args here
    return parser.parse_args()


def get_idx2vec_dict(args, wv):
    glove_path = os.path.join(args.glove_dir, "glove.{}.{}d.txt".format(args.glove_corpus, args.glove_word_size))
    sizes = {'6B': int(4e5), '42B': int(1.9e6), '840B': int(2.2e6), '2B': int(1.2e6)}
    total = sizes[args.glove_corpus]
    idx2vec_dict = {}
    with open(glove_path, 'r') as fh:
        for line in tqdm(fh, total=total):
            array = line.lstrip().rstrip().split(" ")
            word = array[0]
            if word in wv:
                vector = list(map(float, array[1:]))
                idx2vec_dict[wv[word]] = vector
    print("{}/{} of word vocab have corresponding vectors in {}".format(len(idx2vec_dict), len(wv), glove_path))
    return idx2vec_dict


def get_data(args, data_path, is_train):
    with open(data_path, 'r') as fh:
        d = json.load(fh)
        size = sum(len(article['paragraphs']) for article in d['data'])
        pbar = tqdm(range(size))
        f1s = []
        max_num_sents = 0
        max_sent_size = 0
        max_num_words = 0
        max_ques_size = 0
        max_ques_word_size = 0
        max_sent_word_size = 0
        max_word_size = 0

        rx, q, y = [], [], []
        cq = []
        x = []
        cx = []
        ids = []
        idxs = []
        a = []

        word_counter = Counter()
        char_counter = Counter()
        invalid_stop_idx_counter = 0

        for ai, article in enumerate(d['data']):
            x_a, cx_a = [], []
            x.append(x_a)
            cx.append(cx_a)
            for pi, para in enumerate(article['paragraphs']):
                ref = [ai, pi]
                pbar.update(1)
                # context = para['context']
                context_nodes, context_edges = [], []
                for each in para['context_dep']:
                    if each is None:
                        # ignores as non-existent
                        context_nodes.append([])
                        context_edges.append([])
                    else:
                        nodes, edges = each
                        context_nodes.append(nodes)
                        context_edges.append(edges)

                context_words = [[each[0] for each in nodes] for nodes in context_nodes]
                context_chars = [[list(word) for word in sent] for sent in context_words]
                x_a.append(context_words)
                cx_a.append(context_chars)

                max_num_sents = max(max_num_sents, len(context_nodes))
                max_sent_size = max(max_sent_size, max(map(len, context_nodes)))
                max_num_words = max(max_num_words, sum(map(len, context_nodes)))
                max_word_size = max(max_word_size, max(len(word) for sent in context_words for word in sent))
                max_sent_word_size = max(max_sent_word_size, max(len(word) for sent in context_words for word in sent))
                consts = para['context_const']
                # context_words, context_tags, context_starts, context_stops = zip(*context_nodes)
                for qa in para['qas']:
                    question = qa['question']
                    id_ = qa['id']
                    question_dep = qa['question_dep']
                    if question_dep is None:
                        print("unparsed question (ignoring): {}".format(question))
                    question_words = [] if question_dep is None else [each[0] for each in question_dep[0]]
                    question_chars = [[]] if question_dep is None else [list(word) for word in question_words]
                    word_counter.update(word.lower() for sent in context_words for word in sent)
                    char_counter.update(char for sent in context_words for word in sent for char in word)
                    word_counter.update(word.lower() for word in question_words)
                    char_counter.update(char for word in question_chars for char in word)
                    max_ques_size = max(max_ques_size, len(question_words))
                    max_ques_word_size = max(max_ques_word_size, max(map(len, question_chars)))
                    bs = []
                    for answer in qa['answers'][:1]:  # Fix this to use all answers!
                        start_idx = answer['start_idx']
                        stop_idx = answer['stop_idx']
                        # If span is extended further than the sent length
                        if start_idx[1] >= len(context_nodes[start_idx[0]]) or stop_idx[1] > len(context_words[stop_idx[0]]):
                            print(ai, pi)
                            print(context_nodes[start_idx[0]])
                            print(answer['text'])
                            invalid_stop_idx_counter += 1
                            # FIXME : adhoc (answer being last word), not ignoring single question
                            start_idx[1] = len(context_words[start_idx[0]]) - 1
                            stop_idx[1] = start_idx[1] + 1
                        full_span = [start_idx, stop_idx]
                        support_tree = nltk.tree.Tree.fromstring(consts[start_idx[0]])
                        span = (start_idx[1], stop_idx[1])
                        set_span(support_tree)
                        b = int(tree_contains_span(support_tree, span))
                        bs.append(b)

                        max_span, f1 = find_max_f1_span(support_tree, span)
                        f1s.append(f1)

                        rx.append(ref)
                        q.append(question_words)
                        cq.append(question_chars)
                        y.append(full_span)
                        ids.append(id_)
                        idxs.append(len(idxs))
                        a.append(answer['text'])
            if args.debug:
                break
        print("num invalid stop idx: {}".format(invalid_stop_idx_counter))
        print("average f1: {}".format(np.mean(f1s)))
        print("max sent size: {}".format(max_sent_size))
        print("max num words: {}".format(max_num_words))
        print("max num sents: {}".format(max_num_sents))
        print("max ques size: {}".format(max_ques_size))
        print("max sent word size: {}".format(max_sent_word_size))
        print("max ques word size: {}".format(max_ques_word_size))
        print("max word size: {}".format(max_word_size))

        wv = {word: i+2 for i, word in enumerate(word for word, count in word_counter.items() if count >= args.min_word_count)}
        cv = {char: i+2 for i, char in enumerate(char for char, count in char_counter.items() if count >= args.min_char_count)}
        assert NULL not in wv
        assert UNK not in wv
        wv[NULL] = 0
        wv[UNK] = 1
        cv[NULL] = 0
        cv[UNK] = 1

        metadata = {'max_sent_size': max_sent_size,
                    'max_num_words': max_num_words,
                    'max_num_sents': max_num_sents,
                    'max_ques_size': max_ques_size,
                    'max_sent_word_size': max_sent_word_size,
                    'max_ques_word_size': max_ques_word_size,
                    'max_word_size': max_word_size,
                    'word_vocab_size': len(wv),
                    'char_vocab_size': len(cv)}
        data = {'*x': rx, '*cx': rx, 'cq': cq, 'q': q, 'y': y, 'ids': ids, 'idxs': idxs, 'a': a}
        shared = {'x': x, 'cx': cx, 'wv': wv, 'cv': cv}
        return data, shared, metadata


def recursive_replace(l, v, lower=False):
    if isinstance(l, str):
        if lower:
            l = l.lower()
        if l in v:
            return v[l]
        else:
            return 1
    return [recursive_replace(each, v) for each in l]


def apply(data, shared, wv, cv):
    data = {'*x': data['*x'], '*cx': data['*cx'], 'cq': recursive_replace(data['cq'], cv),
            'q': recursive_replace(data['q'], wv, lower=True), 'y': data['y'], 'ids': data['ids'], 'idxs': data['idxs'], 'a': data['a']}
    shared = {'x': recursive_replace(shared['x'], wv, lower=True), 'cx': recursive_replace(shared['cx'], cv), 'wv': shared['wv'], 'cv': shared['cv']}
    return data, shared


def split(data, ratio):
    idx = int(ratio * len(next(iter(data.values()))))
    train_data = {key: val[:idx] for key, val in data.items()}
    dev_data = {key: val[idx:] for key, val in data.items()}
    return train_data, dev_data


def prepro(args):
    train_data_path = os.path.join(args.source_dir, "train-v1.0-aug.json")
    test_data_path = os.path.join(args.source_dir, "dev-v1.0-aug.json")
    data_train, shared_train, metadata_train = get_data(args, train_data_path, True)
    data_test, shared_test, metadata_test = get_data(args, test_data_path, False)

    wv = shared_train['wv']
    cv = shared_train['cv']
    data_train, shared_train = apply(data_train, shared_train, wv, cv)
    data_test, shared_test = apply(data_test, shared_test, wv, cv)
    data_train, data_dev = split(data_train, args.train_ratio)
    shared_test['wv'] = wv
    shared_test['cv'] = cv
    metadata_test['word_vocab_size'] = metadata_train['word_vocab_size']
    metadata_test['char_vocab_size'] = metadata_train['char_vocab_size']

    idx2vec_dict = get_idx2vec_dict(args, wv)
    shared_train['idx2vec'] = idx2vec_dict

    if not os.path.exists(args.target_dir):
        os.makedirs(args.target_dir)

    def save(data, shared, metadata, data_type):
        out_data_path = os.path.join(args.target_dir, "data_{}.json".format(data_type))
        out_shared_path = os.path.join(args.target_dir, "shared_{}.json".format(data_type))
        metadata_path = os.path.join(args.target_dir, "metadata_{}.json".format(data_type))
        with open(out_data_path, 'w') as fh:
            json.dump(data, fh)
        with open(out_shared_path, 'w') as fh:
            json.dump(shared, fh)
        with open(metadata_path, 'w') as fh:
            json.dump(metadata, fh)

    save(data_train, shared_train, metadata_train, 'train')
    save(data_dev, shared_train, metadata_train, 'dev')
    save(data_test, shared_test, metadata_test, 'test')


def main():
    args = get_args()
    prepro(args)

if __name__ == "__main__":
    main()
