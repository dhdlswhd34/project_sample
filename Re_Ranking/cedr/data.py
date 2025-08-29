import torch


def iter_valid_records(model, dataset, run, batch_size):
    batch = {'query_id': [], 'doc_id': [], 'query_tok': [], 'doc_tok': []}
    for qid, did, query_tok, doc_tok in _iter_valid_records(model, dataset, run):
        batch['query_id'].append(qid)
        batch['doc_id'].append(did)
        batch['query_tok'].append(query_tok)
        batch['doc_tok'].append(doc_tok)
        if len(batch['query_id']) == batch_size:
            yield _pack_n_ship(batch)
            batch = {'query_id': [], 'doc_id': [], 'query_tok': [], 'doc_tok': []}
    # final batch
    if len(batch['query_id']) > 0:
        yield _pack_n_ship(batch)


def _iter_valid_records(model, dataset, run):
    ds_queries, ds_docs = dataset
    for qid in run:
        query_tok = model.tokenize(ds_queries[qid])
        for did in run[qid]:
            doc = ds_docs.get(did)
            if doc is None:
                continue
            doc_tok = model.tokenize(doc)
            yield qid, did, query_tok, doc_tok


def _pack_n_ship(batch):
    QLEN = 20
    MAX_DLEN = 800
    DLEN = min(MAX_DLEN, max(len(b) for b in batch['doc_tok']))
    return {
        'query_id': batch['query_id'],
        'doc_id': batch['doc_id'],
        'query_tok': _pad_crop(batch['query_tok'], QLEN),
        'doc_tok': _pad_crop(batch['doc_tok'], DLEN),
        'query_mask': _mask(batch['query_tok'], QLEN),
        'doc_mask': _mask(batch['doc_tok'], DLEN),
    }


def _pad_crop(items, num):
    result = []
    for item in items:
        if len(item) < num:
            item = item + [-1] * (num - len(item))
        if len(item) > num:
            item = item[:num]
        result.append(item)
    return torch.tensor(result).long().cuda()


def _mask(items, num):
    result = []
    for item in items:
        if len(item) < num:
            item = [1. for _ in item] + ([0.] * (num - len(item)))
        if len(item) >= num:
            item = [1. for _ in item[:num]]
        result.append(item)
    return torch.tensor(result).float().cuda()
