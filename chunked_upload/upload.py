# 업로드 메타데이터 생성
class UploadMetaData(APIView):
    authentication_classes = [JWTAuthentication]
    permission_classes = [
        IsUser(
            menu=UsersMenuEnum.EXPLORER,
        )
    ]

    folder_type = None

    def get_response_form(self, user_file_obj):
        file_metadata = user_file_obj.file
        res = {
            "Sample": "Sample"
        }
        return res

    def get_redis_form(self, user_file_obj, users):
        file_metadata = user_file_obj.file
        redis_form = {
            "Sample": "Sample"
        }
        return redis_form

    def make_path_list(self, file_path, folder_id):
        path_list = file_path.split("/")
        users_folder = UsersFolderModel.objects.get(
            users=self.users,
            users_explorer_folder__code=self.folder_type,
        ).seq
        redis_lock = RedisLock()
        target_folder = None

        for path in path_list:
            lock_key = f"folder_lock_{folder_id}_{path}"  # 고유 락 키 생성
            lock = redis_lock.redis_client.lock(
                lock_key, timeout=10
            )  # 락 객체 생성
            max_retries = 5
            retries = 0

            while retries < max_retries:
                if lock.acquire(blocking=True):  # 락을 획득 시도
                    try:
                        dup_folder = FolderClosureModel.objects.filter(
                            ancestor_id=folder_id,
                            ancestor__is_remove=FolderActiveEnum.ACTIVE,
                            descendant__is_remove=FolderActiveEnum.ACTIVE,
                            descendant__name=path,
                            depth=1,
                        )
                        # 중복 확인
                        if dup_folder.exists():
                            # 중복이 발생한 경우
                            dup_folder = dup_folder.first()
                            # 중복 폴더의 ID로 업데이트
                            target_folder = dup_folder.descendant
                            folder_id = dup_folder.descendant.seq
                        else:
                            # 중복이 아닐 경우 폴더 생성
                            serializer = NewFolderSerializer(
                                data={
                                    "name": path,
                                    "parent_id": folder_id,
                                    "users_folder": users_folder,
                                },
                                context={
                                    "users": self.users,
                                    "folder_type": self.folder_type,
                                },
                            )
                            if serializer.is_valid() is False:
                                raise ValidationResponse(serializer)
                            target_folder = serializer.save()
                            folder_id = (
                                target_folder.seq
                            )  # 새로 생성된 폴더의 ID로 업데이트
                    finally:
                        lock.release()  # 락 해제
                    break
                else:
                    retries += 1
                    time.sleep(0.1)

                if retries == max_retries:
                    return False

        # 최종적으로 생성된 폴더 반환
        return target_folder

    def post(self, request):
        self.users = request.user
        data = request.data
        file_name = data.get("file_name")
        path = data.get("path")
        folder_id = data.get("folder_id")
        is_exists = False

        # 물리 디스크 잠금 확인
        if DiskNotificationCache.get("default"):
            return ErrorResponse(
                code="error_user_upload_lock",
                message="업로드 잠김",
            )

        # 폴더 가져오기
        folder = FolderModel.objects.get(seq=folder_id)

        # 이름 체크
        if is_valid_filename(file_name) is False:
            return ErrorResponse(
                code="error_user_file_name",
                message='파일 이름에는 | \\ : * ? " < >를 사용할 수 없습니다.',
            )

        # 파일 path 선정
        with transaction.atomic():
            if path:
                path_name_list = path.split("/")
                for name in path_name_list:
                    if is_valid_filename(name) is False:
                        return ErrorResponse(
                            code="error_user_file_path",
                            message='경로가 잘못되었습니다. 폴더 이름에는 | \\ : * ? " < >를 사용할 수 없습니다.',
                        )

                target_folder = self.make_path_list(path, data["folder_id"])
                if target_folder is False:
                    return ErrorResponse(
                        code="error_user_time_out",
                        message="경로 생성 오류 (time out)",
                    )
                data["folder_id"] = target_folder.seq

        # 중복 file 체크 및 가져오기
        data["upload_name"] = file_name
        file = FileModel.objects.filter(
            upload_hash=data["upload_hash"],
            active=ChunkedUploadEnum.COMPLETE,
        )
        if file.exists():
            file = file.first()
            is_exists = True

        with transaction.atomic():
            # 메타데이터 체크
            serializer = UploadMetaDataSerializer(
                data=data,
                context={
                    "users": self.users,
                    "folder_type": self.folder_type,
                    "file": file,
                },
            )
            if serializer.is_valid() is False:
                raise ValidationResponse(serializer)
            validated_data = serializer.save()
            file_metadata = validated_data["file"]
            users_file = validated_data["users_file"]

            # 사용량 업데이트
            owner_users = (
                folder.users_folder.users
                if self.folder_type is UsersExplorerFolderEnum.SHARE
                else self.users
            )
            explorer_tools = ExplorerTools(owner_users, self.folder_type)
            explorer_tools.set_upload_usage(folder, file_metadata.upload_size)

            # 통계 업데이트
            statistics_tools = StatisticsTools(owner_users)
            statistics_tools.set_upload_stat(users_file, self.folder_type)

            # redis 저장
            key = f"{file_metadata.saved_name}_{self.users.seq}"
            self.redis = UploadCache(key)
            redis_form = self.get_redis_form(users_file, self.users)
            self.redis.set_cache(redis_form)

            # return
            res = self.get_response_form(users_file)

            # 형상관리
            if validated_data.get("new_version", None):
                Logger.file(
                    request,
                    validated_data["new_version"].users_file,
                    LogFileEnum.FILE,
                    self.folder_type,
                    LogFileActionEnum.FILE_VERSIONING,
                )
            contents = Logger.get_log_info(code="version_limit_exceeded")
            if validated_data.get("delete_file", None):
                Logger.file(
                    request,
                    validated_data["delete_file"].users_file,
                    LogFileEnum.FILE,
                    self.folder_type,
                    LogFileActionEnum.FILE_AUTO_REMOVE,
                    contents=contents,
                )
        # 중복 파일 후처리
        if is_exists:
            log_seq = Logger.file(
                request,
                users_file,
                LogFileEnum.FILE,
                self.folder_type,
                LogFileActionEnum.FILE_UPLOAD,
            )
            after_upload_exist.delay(
                file.seq, users_file.seq, self.users.seq, log_seq
            )

        if file_metadata.upload_size == 0:
            log_seq = Logger.file(
                request,
                users_file,
                LogFileEnum.FILE,
                self.folder_type,
                LogFileActionEnum.FILE_UPLOAD,
            )

            Logger.notification(
                users_file.users.domain,
                NotificationCategoryEnum.UPLOAD,
                NotificationEnum.UPLOAD_COMPLETE,
                {"file": users_file.file.upload_name},
                users_file.users,
            )

            # 후처리 기능
            after_upload.delay(
                users_file.file.seq, users_file.seq, self.users.seq, log_seq
            )

        return SuccessResponse(data=res)


# 업로드
class ChunkUploadAppend(APIView):
    authentication_classes = [JWTAuthentication]
    permission_classes = [IsUser(menu=UsersMenuEnum.EXPLORER)]

    content_range_header = "HTTP_X_CONTENT_RANGE"
    content_upload_id_header = "HTTP_X_CONTENT_ID"

    folder_type = None

    def get_response_form(self):
        res = {
            "upload_id": self.upload_info["upload_id"],
            "offset": self.upload_info["offset"],
            "file_size": self.upload_info["file_size"],
            "expire_date": self.cache_data.get_expire(),
        }
        return res

    def chk_complete_file(self, file_object):
        if file_object.chk_file_hash():
            # db 오류코드 반영
            file_object.active = ChunkedUploadEnum.ERROR
            file_object.save()
            # 캐시 삭제
            self.cache_data.del_cache()
            return True
        else:
            file_object.active = ChunkedUploadEnum.WORKING
            file_object.save()
            self.upload_info["active"] = ChunkedUploadEnum.WORKING
            return False

    def upload_complete(self, request, upload_obj):
        # 업로드 완료
        users_file = UsersFileModel.objects.get(file=upload_obj)

        log_seq = Logger.file(
            request,
            users_file,
            LogFileEnum.FILE,
            self.folder_type,
            LogFileActionEnum.FILE_UPLOAD,
        )

        Logger.notification(
            users_file.users.domain,
            NotificationCategoryEnum.UPLOAD,
            NotificationEnum.UPLOAD_COMPLETE,
            {"file": upload_obj.upload_name},
            users_file.users,
        )

        # 후처리 기능
        after_upload.delay(
            upload_obj.seq, users_file.seq, self.users.seq, log_seq
        )

    def get(self, request, file_id):
        self.users = request.user

        users_file = UsersFileModel.objects.get(seq=file_id)
        file = users_file.file

        key = f"{file.saved_name}_{self.users.seq}"
        self.cache_data = UploadCache(key)
        upload_info = self.cache_data.get_cache()
        if upload_info:
            upload_info.pop("user_id")
            upload_info.pop("file_id")
            return SuccessResponse(data=upload_info)
        else:
            return ErrorResponse(
                code="error_user_expired_file", message="만료된 파일입니다."
            )

    def post(self, request):
        self.users = request.user
        data = request.META

        serializer = ChunkUploadAppendSerializer(
            data=data, context={"users": self.users, "contents": request.body}
        )
        if serializer.is_valid() is False:
            raise ValidationResponse(serializer)

        upload_obj = serializer.validated_data["upload_obj"]
        chunk_contents = serializer.validated_data["chunk_contents"]
        self.upload_info = serializer.validated_data["upload_info"]
        self.cache_data = serializer.validated_data["cache_data"]

        # 파일 업로드 완료 체크
        with transaction.atomic():
            # 파일 저장 (append)
            if upload_obj.append_chunk(chunk_contents, is_save=False):
                return ErrorResponse(
                    code="fail_user_upload_save",
                    message="upload save error",
                )

            if self.upload_info["offset"] == self.upload_info["file_size"]:
                # 완료 확인
                if self.chk_complete_file(upload_obj) is True:
                    return ErrorResponse(
                        code="error_user_file_hash",
                        message="file_hash not match",
                    )

                # 업로드 완료
                self.upload_complete(request, upload_obj)

        # redis 저장 or 갱신
        self.cache_data.set_cache(self.upload_info)

        # 결과 return
        res = self.get_response_form()
        response = SuccessResponse(data=res)
        return response