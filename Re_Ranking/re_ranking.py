from .cedr.data import iter_valid_records
from tqdm import tqdm
from .cedr.modeling import CedrKnrmRanker
import random
import torch


class CedrSearch():
    def __init__(self):
        self.WEIGHT_FILE = 'weights.p'
        self.g_model = CedrKnrmRanker().cuda()
        self.g_model.load(self.WEIGHT_FILE)

        self.SEED = 42
        torch.manual_seed(self.SEED)
        torch.cuda.manual_seed_all(self.SEED)
        random.seed(self.SEED)

        torch.backends.cudnn.enabled = True
        # False:cudnn library를 사용하지 않게 만듬(cudnn을 사용하지 않으면 속도가 많이 느려집니다.)

        torch.backends.cudnn.benchmark = True
        # True 인 경우 cuDNN이 다중 회선 알고리즘을 벤치마킹하고 가장 빠른 알고리즘을 선택하도록 한다.
        # 내장된 cudnn 자동 튜너를 활성화하여, 하드웨어에 맞게 사용할 최상의 알고리즘(텐서 크기나 conv 연산에 맞게)을 찾는다.
        # 입력 이미지 크기가 자주 변하지 않는다면, 초기 시간이 소요되지만 일반적으로 더 빠른 런타임의 효과를 볼 수 있다.
        # 그러나, 입력 이미지 크기가 반복될 때마다 변경된다면 런타임성능이 오히려 저하될 수 있다.

    def run_model(self, model, dataset, run, desc='valid'):
        BATCH_SIZE = 16
        rerank_run = {}

        with torch.no_grad(), tqdm(total=sum(len(r) for r in run.values()), ncols=80, desc=desc, leave=False) as pbar:
            model.eval()
            for records in iter_valid_records(model, dataset, run, BATCH_SIZE):
                scores = model(records['query_tok'], records['query_mask'], records['doc_tok'], records['doc_mask'])
                for qid, did, score in zip(records['query_id'], records['doc_id'], scores):
                    rerank_run.setdefault(qid, {})[did] = score.item()
                pbar.update(len(records['query_id']))

        for qid in rerank_run:
            scores = list(sorted(rerank_run[qid].items(), key=lambda x: (x[1], x[0]), reverse=True))
            return scores

    # CEDR 모델 검색 기능 수행
    def search(self, req_data):
        scores = self.run_model(self.g_model, req_data['objArrDataset'], req_data['objArrRun'], desc=req_data['desc'])

        if scores is None:
            return {}

        return_data = {
            'result': scores
        }
        return return_data
