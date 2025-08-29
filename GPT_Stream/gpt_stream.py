from django.http.response import JsonResponse
from django.http.response import StreamingHttpResponse

from rest_framework.views import APIView
from rest_framework.response import Response

import json
import pandas as pd

from chatgpt.common.db import DatabaseController
from chatgpt.common.auth import jwt_token_verification, check_gpt_seq, set_event_log, get_user_info_seq
from chatgpt.common.gpt import ChatGptApi
from chatgpt.common.gpt_utility import gen_message

event_type = "Chat"

def check_request_validation(user_info, gpt_id, mode):
    # user 확인
    db_con = DatabaseController()

    # gpt_id 확인
    if gpt_id:
        sql = """
            SELECT a.seq, a.gpt_limit
            FROM member a, gpt_history b, gpt_log c
            WHERE a.email = %s AND a.seq = b.member_seq AND b.seq = %s AND b.gpt_log_seq = c.seq AND c.content_category = %s
        """
        data_tuple = (user_info["email"], gpt_id, mode)
    else:
        sql = """
            SELECT seq, gpt_limit
            FROM member
            WHERE email = %s
        """
        data_tuple = (user_info["email"],)

    try:
        res_db = db_con.query_one(sql, data_tuple)
        if res_db["seq"]:
            return res_db
    except Exception:
        return False

def get_user_total_price(seq):
    db_con = DatabaseController()
    sql = """
        SELECT SUM(total_price) as user_price
        FROM gpt_log
        WHERE member_seq = %s
    """
    res_db = db_con.query_one(sql, (seq,))
    return res_db["user_price"]

def check_user_limit(user):
    user_price = get_user_total_price(user["seq"])

    if user_price is None:
        return 0

    if user["gpt_limit"] > user_price:
        return user_price
    else:
        return False

class ChatGpt(APIView):
    @jwt_token_verification
    def post(self, request):
        data = json.loads(request.body)

        user = check_request_validation(self.user_info, data["gpt_id"], "Chat")
        if user is False:
            m = "request_validation error"
            msg = {"status": "error", "msg": m}
            set_event_log(self.user_info["email"], event_type, msg)
            return Response({
                'status': 'error',
                'message': 'gpt_id error'
            })

        price = check_user_limit(user)
        if price is False:
            m = 'gpt_limit error'
            msg = {"status": "error", "msg": m}
            set_event_log(self.user_info["email"], event_type, msg)
            return Response({
                'status': 'error',
                'message': 'gpt_limit error'
            })

        gpt = ChatGptApi()
        gpt.user_info = self.user_info

        res = gpt.get_chat_gpt(
            chat_message=data["data"],
            user=user["seq"],
            gpt_id=data["gpt_id"],
            model=data["model"],
            search=data["search"]
        )

        if res:
            m = 'response chat'
            msg = {"status": "success", "msg": m}
            set_event_log(self.user_info["email"], event_type, msg)
            return JsonResponse(res)
        else:
            return Response({
                'status': 'error'
            })

class CompleteGpt(APIView):
    @jwt_token_verification
    def post(self, request):
        data = json.loads(request.body)

        user = check_request_validation(self.user_info, data["gpt_id"], "complete")
        if user is False:
            return Response({
                'status': 'error',
                'message': 'gpt_id error'
            })

        price = check_user_limit(user)
        if price is False:
            return Response({
                'status': 'error',
                'message': 'gpt_limit error'
            })

        gpt = CompleteGptApi()
        gpt.user_info = self.user_info
        res = gpt.get_complete_gpt(
            prompt=data["data"],
            user=user["seq"],
            gpt_id=data["gpt_id"],
            model=data["model"],
            search=data["search"]
        )

        if res:
            return JsonResponse(res)
        else:
            return Response({
                'status': 'error'
            })

# 히스토리 리스트
class GptHistoryList(APIView):
    @jwt_token_verification
    def get(self, request):
        db_con = DatabaseController()

        content_category = request.GET.get("category", "")
        if content_category:
            sql = """
            SELECT a.seq as gpt_history_seq, history_nm, content_category
            FROM gpt_history a, member b, gpt_log c
            WHERE b.email = %s AND b.seq = a.member_seq AND c.seq = a.gpt_log_seq  AND c.content_category = %s
            order by a.seq desc
            """

            data_tuple = (self.user_info['email'], content_category,)
        else:
            sql = """
            SELECT a.seq as gpt_history_seq, history_nm, content_category
            FROM gpt_history a, member b, gpt_log c
            WHERE b.email = %s AND b.seq = a.member_seq AND c.seq = a.gpt_log_seq
            order by a.seq desc
            """

            data_tuple = (self.user_info['email'],)

        try:
            res_db = db_con.query_all(sql, data_tuple)
            m = 'get history list'
            msg = {"status": "success", "msg": m}
            set_event_log(self.user_info["email"], "chat_history", msg)
            return JsonResponse({"gpt_list": res_db})
        except Exception:
            m = f'get history list error {Exception}'
            msg = {"status": "error", "msg": m}
            set_event_log(self.user_info["email"], "chat_history", msg)
            return Response({
                'status': 'error'
            })

    @jwt_token_verification
    def delete(self, request, gpt_list_id):
        if check_gpt_seq(self.user_info, gpt_list_id) is False:
            return Response({
                'status': 'error',
                'message': 'gpt_list_id is not exist'
            })

        db_con = DatabaseController()

        sql = """
        DELETE FROM gpt_history
        WHERE seq IN (
        SELECT a.seq
        FROM gpt_history a, member b
        WHERE b.email = %s AND b.seq = a.member_seq AND a.seq = %s
        );
        """

        data_tuple = (self.user_info['email'], gpt_list_id,)

        if db_con.execute(sql, data_tuple):
            m = 'del history list'
            msg = {"status": "success", "msg": m}
            set_event_log(self.user_info["email"], "chat_history", msg)
            return Response({
                'status': 'success'
            })

        m = 'del history list error'
        msg = {"status": "error", "msg": m}
        set_event_log(self.user_info["email"], "chat_history", msg)
        return Response({
            'status': 'error'
        })

    @jwt_token_verification
    def put(self, request, gpt_list_id):
        data = json.loads(request.body)

        if check_gpt_seq(self.user_info, gpt_list_id) is False:
            m = 'mod history name id error'
            msg = {"status": "error", "msg": m}
            set_event_log(self.user_info["email"], "chat_history", msg)
            return Response({
                'status': 'error',
                'message': 'gpt_list_id error'
            })

        db_con = DatabaseController()

        sql = """
        UPDATE gpt_history
        SET history_nm = %s
        WHERE seq = %s
        """
        data_tuple = (data["history_nm"], gpt_list_id,)

        if db_con.execute(sql, data_tuple):
            m = 'mod history list'
            msg = {"status": "success", "msg": m}
            set_event_log(self.user_info["email"], "chat_history", msg)
            return Response({
                'status': 'success'
            })
        m = 'mod history name error'
        msg = {"status": "error", "msg": m}
        set_event_log(self.user_info["email"], "chat_history", msg)
        return Response({
            'status': 'error'
        })

# history 내용 가져오기
class GptHistory(APIView):
    @jwt_token_verification
    def get(self, request, gpt_id, content_category):
        db_con = DatabaseController()

        sql = """
        SELECT a.seq AS gpt_history_seq, c.chat, l.content_category
        FROM gpt_history a
        INNER JOIN member b ON b.seq = a.member_seq
        INNER JOIN gpt_chat c ON a.seq = c.gpt_history_seq
        INNER JOIN gpt_log l ON l.seq = a.gpt_log_seq AND l.content_category = %s
        WHERE b.email = %s AND a.seq = %s;
        """
        data_tuple = (content_category, self.user_info['email'], gpt_id, )
        try:
            res_db = db_con.query_one(sql, data_tuple)
            res_db["chat"] = json.loads(res_db["chat"])

            if res_db:
                _df = pd.DataFrame(res_db['chat'])
                _df['num'] = _df.index
                _chat = _df.to_dict('records')
                res_db['chat'] = _chat
                m = 'get history'
                msg = {"status": "success", "msg": m}
                set_event_log(self.user_info["email"], "chat_history", msg)
                return JsonResponse(res_db)
        except Exception:
            m = 'get history error'
            msg = {"status": "error", "msg": m}
            set_event_log(self.user_info["email"], "chat_history", msg)
            return Response({
                'status': 'error'
            })

class ChatGptStream(APIView):
    @jwt_token_verification
    def post(self, request):
        data = json.loads(request.body)

        user = check_request_validation(self.user_info, data["gpt_id"], "Chat")
        if user is False:
            m = "request_validation error"
            msg = {"status": "error", "msg": m}
            set_event_log(self.user_info["email"], event_type, msg)
            return StreamingHttpResponse(gen_message(state='error', content='gpt_id error'), status=200, content_type='text/event-stream ')

        price = check_user_limit(user)
        if price is False:
            m = 'gpt_limit error'
            msg = {"status": "error", "msg": m}
            set_event_log(self.user_info["email"], event_type, msg)
            return StreamingHttpResponse(gen_message(state='error', content='gpt_limit error'), status=200, content_type='text/event-stream ')

        gpt = ChatGptApi()
        gpt.user_info = self.user_info

        stream = gpt.get_chatgpt_stream(
            chat_message=data["data"],
            user=user["seq"],
            gpt_id=data["gpt_id"],
            model=data["model"],
            search=data["search"],
            mode=data["mode"]
        )

        response = StreamingHttpResponse(stream, status=200, content_type='text/event-stream')
        response['Cache-Control'] = 'no-cache'
        response["X-Accel-Buffering"] = "no"
        response["Content-Length"] = None

        return response
