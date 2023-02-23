import dataclasses
import enum
import functools
import typing
from dataclasses import dataclass
from datetime import datetime
from functools import partial
from typing import Any, TypeAlias, Iterable

import dateutil.parser
import requests
from py_utils import utils
from py_utils.utils import args_asdict

_DEBUG_ = True

FieldsList: TypeAlias = str
ResultCode: TypeAlias = int
Params: TypeAlias = dict[str, str]
operation_id: TypeAlias = str

href: TypeAlias = str
disk_path: TypeAlias = str
public_key_or_path: TypeAlias = str

http_method: TypeAlias = typing.Literal["PUT", "GET", "POST", "PATCH", "DELETE"]

T = typing.TypeVar("T")


class RequestError(Exception):
    ...


class Request:
    disk: "Disk"
    method: http_method
    href_api: href
    params: dict[str, ...]
    response_body: dict[str, ...]
    status_code: int
    body: ...

    _cache: list[dict[str, ...], ...]

    def __init__(
            self, disk: "Disk", method: http_method, href_api: href, params: dict, body=None
    ):
        self.disk = disk
        self.method = method
        self.href_api = href_api
        self.params = params
        self.headers = {
            "Accept": "*/*",
            "Depth": "1",
            "Authorization": f"OAuth {self.disk.token}",
        }
        self.url = "https://cloud-api.yandex.net" + href_api
        self.body = body
        self._cache = []
        self.resp_count = 0
        self.response_body = self._get()

    # def _get2(
    #     self,
    #     params: dict = None,
    # ) -> dict[str, ...]:
    #
    #     if params is None:
    #         params = self.params
    #
    #     if len(self._cache) > self.resp_count:
    #         return self._cache[self.resp_count]
    #
    #     headers = {
    #         "Accept": "*/*",
    #         "Depth": "1",
    #         "Authorization": f"OAuth {self.disk.token}",
    #     }
    #     url = "https://cloud-api.yandex.net" + self.href_api
    #
    #     params = {
    #         key: str(value)
    #         for key, value in params.items()
    #         if value is not None and not key.startswith("_")
    #     }
    #     response = requests.request(
    #         method=self.method, url=url, headers=headers, params=params
    #     )
    #     self.status_code = response.status_code
    #     if response.status_code >= 400:
    #         raise RequestError(ErrorInfo(response.json()))
    #
    #     response = response.json()
    #
    #     self._cache.append(response)
    #
    #     return response

    def _get(
            self,
            params: dict = None,
    ) -> dict[str, ...]:

        if params is None:
            params = self.params

        if len(self._cache) > self.resp_count:
            return self._cache[self.resp_count]

        response = self.disk.http_request(
            method=self.method, href_api=self.href_api, params=params
        )
        self.status_code = response.status_code

        response = response.json()
        self._cache.append(response)

        return response

    def get_embedded(self) -> Iterable[dict[str, ...]]:
        def find_root_items(response):
            value = response
            if "_embedded" in value:
                value = value["_embedded"]
            return value

        self.resp_count = offset = item_count = 0
        params = self.params.copy()

        while (
                (response := self._get(params)) is not None
                and (root := find_root_items(response))
                and (items := root["items"])
                and len(items) > 0
        ):
            self.disk.on_event_before(
                "get_embedded",
                request_data=response,
                params=params,
            )
            for item in items:
                yield item
                self.disk.on_event_after(
                    "get_embedded",
                    item_count,
                    request_data=response,
                    params=params,
                )
                item_count += 1
            self.resp_count += 1
            offset += len(items)
            params["offset"] = offset


# def on_call_event(method):
#     @functools.wraps(method)
#     def wrap(self, *args, **kwargs):
#         self.on_event_before(method.__name__, *args, **kwargs)
#         result = method(self, *args, **kwargs)
#         self.on_event_after(method.__name__, result, *args, **kwargs)
#         return result
#
#     return wrap


class ResourceIterator(typing.Generic[T]):
    def __init__(self, request=None):
        self.request: "Request" = request

    def __set_name__(self, owner_type, field_name):
        self.name = field_name
        self.owner_type = owner_type
        annotations = utils.full_annotations(owner_type)
        self.item_type = annotations[field_name].__args__[0]

    def __set__(self, instance, value: tuple):
        self.value, self.request = value
        self.instance = instance

    def __get__(self, owner, owner_type) -> Iterable[T]:
        for resource in self.request.get_embedded():
            yield self.item_type(self.request, resource)


def request_map(cls=None, /, *, keys_rename: dict[str, str] = None):
    """

    Parameters
    ----------
    cls :
    keys_rename : Словарь переименований ключей входного словаря в поля класса,
        ключ - значение ключа входного словаря
        значение - имя поля класса

    Returns
    -------

    """

    def __init__(self, request: "Request", from_dict: dict = None):
        nonlocal keys_rename
        if from_dict is None:
            from_dict = request.response_body
        for key_dict, value in from_dict.items():
            attr_name = key_dict
            if key_dict in keys_rename:
                attr_name = keys_rename[key_dict]
            annotations = utils.full_annotations(self)
            if attr_name in annotations:
                ann_type = utils.get_origin_type(annotations[attr_name])
                try:
                    if "ResourceIterator" in repr(ann_type):
                        desc_value = ann_type(request)
                        desc_value.__set_name__(type(self), attr_name)
                        # TODO: Дескриптор заработал только через класс, возможные проблемы?
                        setattr(self.__class__, attr_name, desc_value)
                        value = (value, request)
                    elif hasattr(ann_type, "__request_map__"):
                        # value = ann_type(value, request)
                        value = ann_type(request, value)
                    elif not isinstance(value, ann_type):
                        if (ann_type == datetime) and isinstance(value, str):
                            value = dateutil.parser.parse(value)
                        else:
                            value = ann_type(value)
                except Exception:
                    ...
            setattr(self, attr_name, value)

    def __repr__(self):
        return (
                f"{cls.__name__}: ("
                + f", ".join(
            (
                f"{key}:{repr(getattr(self, key))}"
                for key in dir(self)
                if not key.startswith("__")
            )
        )
                + ")"
        )

    if cls is None:
        return partial(request_map, keys_rename=keys_rename)

    if keys_rename is None:
        keys_rename = {}

    cls.__request_map__ = {}
    cls.__init__ = __init__
    cls.__repr__ = __repr__
    return cls


@request_map
class UserInfo:
    country: str
    login: str
    display_name: str
    uid: str


@request_map
class CommentIds:
    private_resource: str  # (string, optional): <Идентификатор комментариев для приватных ресурсов.>,
    public_resource: str  # (string, optional): <Идентификатор комментариев для публичных ресурсов.>


@request_map
class SystemFolders:
    odnoklassniki: str  # (string, optional): <Путь к папке "Социальные сети/Одноклассники".>,
    google: str  # (string, optional): <Путь к папке "Социальные сети/Google+".>,
    instagram: str  # (string, optional): <Путь к папке "Социальные сети/Instagram".>,
    vkontakte: str  # (string, optional): <Путь к папке "Социальные сети/ВКонтакте".>,
    attach: str  # (string, optional): <Путь к папке "Почтовые вложения".>,
    mailru: str  # (string, optional): <Путь к папке "Социальные сети/Мой Мир".>,
    downloads: str  # (string, optional): <Путь к папке "Загрузки".>,
    applications: str  # (string, optional): <Путь к папке "Приложения".>,
    facebook: str  # (string, optional): <Путь к папке "Социальные сети/Facebook".>,
    social: str  # (string, optional): <Путь к папке "Социальные сети".>,
    messenger: str  # (string, optional): <Путь к папке "Файлы Мессенджера".>,
    calendar: str  # (string, optional): <Путь к папке "Материалы встреч".>,
    photostream: str  # (string, optional): <Путь к папке "Фотокамера".>,
    screenshots: str  # (string, optional): <Путь к папке "Скриншоты".>,
    scans: str  # (string, optional): <Путь к папке "Сканы".>


@request_map
class DiskInfo:
    max_file_size: int  # Максимальный поддерживаемый размер файла.>,
    paid_max_file_size: int  # <Максимальный поддерживаемый размер файла для платного аккаунта.>,
    total_space: int  # <Общий объем диска (байт)>,
    trash_size: int  # Общий размер файлов в Корзине (байт). Входит в used_space.>,
    is_paid: bool  # <Признак наличия купленного места.>,
    used_space: int  # Используемый объем диска (байт)>,
    system_folders: SystemFolders
    user: UserInfo
    unlimited_autoupload_enabled: bool  # <Признак включенной безлимитной автозагрузки с мобильных устройств.>,
    revision: int  # <Текущая ревизия Диска>


@request_map
class ExifInfo:
    date_time: datetime
    gps_longitude: dict  # <Координата съемки (долгота).>,
    gps_latitide: dict  # <Координата съемки (широта).>


@request_map
class ShareInfo:
    is_root: bool  # (boolean, optional): <Признак того, что папка является корневой в группе>,
    is_owned: bool  # (boolean, optional): <Признак, что текущий пользователь является владельцем общей папки>,
    rights: str  # (string): <Права доступа>


@request_map
class ResourceShort:
    resource_id: str  # (string, optional): <Идентификатор ресурса>,
    exif: ExifInfo  # , optional),
    type: str  # (string): <Тип>,
    revision: int  # (integer, optional): <Ревизия Диска в которой этот ресурс был изменён последний раз>,
    path: str  # (string): <Путь к ресурсу>,
    name: str  # (string): <Имя>,
    created: datetime  # (string): <Дата создания>,
    modified: datetime  # (string): <Дата изменения>,
    comment_ids: CommentIds  # , optional)


@request_map
class FileShort(ResourceShort):
    antivirus_status: str  # (object, optional): <Статус проверки антивирусом>,
    file: str  # (string, optional): <URL для скачивания файла>,
    size: int  # (integer, optional): <Размер файла>,
    media_type: str  # (string, optional): <Определённый Диском тип файла>,
    mime_type: str  # (string, optional): <MIME-тип файла>,
    md5: str  # (string, optional): <MD5-хэш>,
    sha256: str  # (string, optional): <SHA256-хэш>,


@request_map(keys_rename={"_embedded": "embedded"})
class Resource(ResourceShort):
    embedded: "ResourceList"
    "Список вложенных ресурсов"


@request_map
class File(FileShort):
    photoslice_time: datetime
    "(string, optional): <Дата создания фото или видео файла>"
    custom_properties: dict
    "(object, optional): <Пользовательские атрибуты ресурса>"
    preview: str
    "(string, optional): <URL превью файла>"


@request_map
class ResourceList:
    sort: str
    "(string, optional): <Поле, по которому отсортирован список>"
    items: ResourceIterator[ResourceShort]
    "Iterable[ResourceShort] <Элементы списка>"
    limit: int
    "(integer, optional): <Количество элементов на странице>"
    offset: int
    "(integer, optional): <Смещение от начала списка>"
    path: str
    "(string): <Путь к ресурсу, для которого построен список>"
    total: str
    "(integer, optional): <Общее количество элементов в списке>"


@request_map
class TrashResourceShort(ResourceShort):
    origin_path: str
    "(string, optional): <Путь откуда был удалён ресурс>"
    deleted: datetime
    "(string, optional): <Дата добавления в корзину(для ресурсов в корзине)>"


@request_map(keys_rename={"_embedded": "embedded"})
class TrashResource(TrashResourceShort):
    embedded: "TrashResourceList"


@request_map
class TrashResourceList(ResourceList):
    items: ResourceIterator[TrashResourceShort]
    "<Элементы списка>"


@request_map
class LastUploadedResourceList:
    items: ResourceIterator[ResourceShort]
    "(Array[Resource]): <Элементы списка>"
    limit: int
    "(integer, optional): <Количество элементов на странице"


@request_map
class FilesResourceList:
    items: ResourceIterator[FileShort]  # (Array[Resource]): <Элементы списка>,
    limit: int  # (integer, optional): <Количество элементов на странице>,
    offset: int  # (integer, optional): <Смещение от начала списка>


@request_map
class UserPublicInformation:
    login: str
    "(string, optional): <Логин.>"
    display_name: str
    "(string, optional): <Отображаемое имя пользователя.>"
    uid: str
    "(string, optional): <Идентификатор пользователя."


@request_map
class PublicResource(Resource):
    views_count: int
    "Счетчик просмотров публичного ресурса>"
    owner: UserPublicInformation


@request_map
class PublicResourceList(Resource):
    sort: str
    "(string, optional): <Поле, по которому отсортирован список>"
    public_key: str
    "(string): <Ключ опубликованного ресурса>"
    items: ResourceIterator[ResourceShort]
    "<Элементы списка>"
    limit: int
    "(integer, optional): <Количество элементов на странице>"
    offset: int
    "(integer, optional): <Смещение от начала списка>"
    path: str
    "(string): <Путь опубликованного ресурса>"
    total: int
    "(integer, optional): <Общее количество элементов в списке>"


@request_map
class PublicResourcesList(Resource):
    """
    Список опубликованных ресурсов
    """

    items: ResourceIterator[ResourceShort]  # (Array[Resource]): <Элементы списка>,
    type: str  # (string, optional): <Значение фильтра по типу ресурсов>,
    limit: int  # (integer, optional): <Количество элементов на странице>,
    offset: int  # (integer, optional): <Смещение от начала списка>


@request_map
class ResourceUploadLink:
    operation_id: str  # (string): <Идентификатор операции загрузки файла>,
    href: str  # (string): <URL>,
    method: str  # (string): <HTTP-метод>,
    templated: str  # (boolean, optional): <Признак шаблонизированного URL>


@request_map
class ErrorInfo:
    message: str
    "Человекочитаемое описание ошибки>"
    description: str
    "<Техническое описание ошибки>"
    error: str
    "Уникальный код ошибки>"
    reason: str
    "Причина срабатывания лимита."
    limit: int
    "Значение лимита."


class HttpStatus(enum.Enum):
    done = enum.auto()
    inProgress = enum.auto()
    error = enum.auto()


@request_map
class Link:
    href: str
    method: str  # <HTTP-метод>
    templated: bool  # <Признак шаблонизированного URL>
    operation_id: str  # (string): Идентификатор асинхронной операции
    status: HttpStatus = HttpStatus.done


@dataclass(unsafe_hash=True, frozen=True)
class Disk:
    token: str = dataclasses.field(hash=True)

    # def on_event_before(self, callfn_name: str, /, *args, **kwargs):
    #     ...
    #
    # def on_event_after(self, callfn_name: str, result: Any, /, *args, **kwargs):
    #     ...

    def http_request(
            self, method: str, href_api: str, params: dict = None, **kwargs
    ) -> requests.Response:

        headers = {
            "Accept": "*/*",
            "Depth": "1",
            "Authorization": f"OAuth {self.token}",
        }
        url = "https://cloud-api.yandex.net" + href_api

        if params is None:
            params = {}
        # params.update(kwargs)
        params = {
            key: str(value)
            for key, value in params.items()
            if value is not None and not key.startswith("_")
        }
        response = requests.request(
            method=method, url=url, headers=headers, params=params, **kwargs
        )

        if response.status_code >= 400:
            raise RequestError(ErrorInfo(response.json()))

        return response

    # @on_call_event
    def resource_info(
            self,
            path: str | ResourceShort,
            *,
            fields: FieldsList = None,
            limit: int = None,
            offset: int = None,
            preview_crop: bool = None,
            preview_size: str = None,
            sort: str = None,
    ) -> Resource:
        """
        Получить метаинформацию о файле или каталоге

        Parameters
        ----------
        config :
        path : Путь к ресурсу
        fields : Список возвращаемых атрибутов
        limit : Количество выводимых вложенных ресурсов.
        offset : Смещение от начала списка вложенных ресурсов.
        preview_crop : Разрешить обрезку превью.
        preview_size : Размер превью.
        sort : Поле для сортировки вложенных ресурсов.

        Returns
        -------

        """

        params = args_asdict({"self": None})
        if isinstance(path, ResourceShort):
            params["path"] = path.path

        request = Request(self, "GET", "/v1/disk/resources", params=params)
        return Resource(request)

    # @on_call_event
    def remove_resource(
            self,
            path: str | ResourceShort,
            fields: str = None,
            md5: str = None,
            permanently: bool = None,
            force_async: bool = None,
    ) -> Link | None:
        """
        Удаляет ресурс
        По умолчанию удалит ресурс в Корзину.
        Чтобы удалить ресурс не помещая в корзину, следует указать параметр permanently=true.
        Parameters
        ----------
        path :
        md5 :
        permanently :

        Returns
        -------
        Если удаление происходит асинхронно, то вернёт ответ со статусом 202 и ссылкой на асинхронную операцию.
        Иначе вернёт ответ со статусом 204 и пустым телом.

        """
        params = args_asdict({"self": None})
        if isinstance(path, ResourceShort):
            params["path"] = path.path

        request = Request(self, "DELETE", "/v1/disk/resources", params)
        if request.status_code == 204:
            return None
        return Link(request)

    # @on_call_event
    def move_resource(
            self,
            path: str | ResourceShort,
            target: str | ResourceShort,
            *,
            overwrite: bool = None,
            fields: str = None,
            force_async: bool = None,
    ) -> Link:
        """
        Переместить ресурс
        Parameters
        ----------
        path :  Путь к перемещаемому ресурсу.
        target : Путь к создаваемому ресурсу.
        overwrite : Перезаписать существующий ресурс
        fields : Список возвращаемых атрибутов

        Returns
        -------
        Если перемещение происходит асинхронно, то вернёт ответ с кодом 202 и ссылкой на асинхронную операцию.
        Иначе вернёт ответ с кодом 201 и ссылкой на созданный ресурс.
        """

        if isinstance(path, ResourceShort):
            path = path.path
        if isinstance(target, ResourceShort):
            target = target.path
        params = args_asdict({"self": None, "path": "from", "target": "path"})
        request = Request(self, "POST", "/v1/disk/resources/move", params)
        return Link(request)

    # @on_call_event
    def copy_resource(
            self,
            path: str | ResourceShort,
            target: str | ResourceShort,
            *,
            overwrite: bool = False,
            fields: str = None,
            force_async: bool = None,
    ) -> Link:
        """
        Создать копию ресурса
        Parameters
        ----------
        path :  Путь к копируемому ресурсу.
        target : Путь к создаваемому ресурсу.
        overwrite : Перезаписать существующий ресурс
        fields : Список возвращаемых атрибутов

        Returns
        -------
        Если копирование происходит асинхронно, то вернёт ответ с кодом 202 и ссылкой на асинхронную операцию.
        Иначе вернёт ответ с кодом 201 и ссылкой на созданный ресурс.
        """

        if isinstance(path, ResourceShort):
            path = path.path
        if isinstance(target, ResourceShort):
            target = target.path

        params = args_asdict({"self": None, "path": "from", "target": "path"})
        request = Request(self, "POST", "/v1/disk/resources", params)
        return Link(request)

    # @on_call_event
    def update_resource(
            self, path: str | ResourceShort, body: Any, *, fields: str = None
    ) -> ResourceShort:
        """
        Обновить пользовательские данные
        Parameters
        ----------
        path : Путь к ресурсу
        body :
        fields :

        Returns
        -------

        """
        if isinstance(path, ResourceShort):
            path = path.path
        params = args_asdict({"self": None, "body": None})
        request = Request(self, "PATCH", "/v1/disk/resources", params, body=body)
        return ResourceShort(request)

    # @on_call_event
    def mkdir(self, path: str | ResourceShort, *, fields: str = None) -> Link:
        """
        Создает папку
        Parameters
        ----------
        fields :
        path : Имя папки

        Returns
        -------

        """
        if isinstance(path, ResourceShort):
            path = path.path
        params = args_asdict({"self": None})
        request = Request(self, "PUT", "/v1/disk/resources", params)
        return Link(request)

    # @on_call_event
    def download_resource(
            self, path: str | ResourceShort, *, fields: str = None
    ) -> Link:
        """
        Получить ссылку на скачивание файла
        Parameters
        ----------
        path : Путь к ресурсу
        fields :

        Returns
        -------
        """
        if isinstance(path, ResourceShort):
            path = path.path
        params = args_asdict({"self": None})
        request = Request(self, "GET", "/v1/disk/resources/download", params)
        return Link(request)

    # @on_call_event
    def download_public_resource(
            self, public_key: str, *, path: str = None, fields: str = None
    ) -> Link:
        """
        Получить ссылку на скачивание файла
        Parameters
        ----------
        path : Путь к ресурсу
        fields :

        Returns
        -------
        """

        params = args_asdict({"self": None})
        request = Request(self, "GET", "/v1/disk/public/resources/download", params)
        return Link(request)

    # @on_call_event
    def files(
            self,
            *,
            fields: FieldsList = None,
            media_type: str = None,
            limit: int = None,
            offset: int = None,
            preview_crop: bool = None,
            preview_size: str = None,
            sort: str = None,
    ) -> FilesResourceList:
        """
        Получить список всех файлов упорядоченный по имени

        Parameters
        ----------
        fields : Список возвращаемых атрибутов
        media_type: Фильтр по типу медиа
        preview_crop : Разрешить обрезку превью.
        preview_size : Размер превью.
        sort : Поле для сортировки ресурсов.

        Returns
        -------
        Генератор по файлам диска

        """

        params = args_asdict({"self": None})
        request = Request(self, "GET", "/v1/disk/resources/files", params)
        return FilesResourceList(request)

    # @on_call_event
    def last_uploaded(
            self,
            *,
            limit: int = None,
            fields: FieldsList = None,
            media_type: str = None,
            preview_crop: bool = None,
            preview_size: str = None,
    ) -> LastUploadedResourceList:
        """
        Получить список всех файлов упорядоченный по дате загрузки

        Parameters
        ----------

        fields : Список возвращаемых атрибутов
        media_type : Фильтр по типу медиа
        preview_crop : Разрешить обрезку превью.
        preview_size : Размер превью.
        sort : Поле для сортировки ресурсов.

        Returns
        -------
        Генератор по последним загруженным файлам диска

        """
        params = args_asdict({"self": None})
        request = Request(self, "GET", "/v1/disk/resources/last-uploaded", params)
        return LastUploadedResourceList(request)

    # @on_call_event
    def public(
            self,
            *,
            fields: FieldsList = None,
            limit: int = None,
            offset: int = None,
            preview_crop: bool = None,
            preview_size: str = None,
            type_resource: str = None,
    ) -> PublicResourcesList:
        """
        Получить список опубликованных ресурсов

        Parameters
        ----------
        fields : Список возвращаемых атрибутов
        media_type: Фильтр по типу медиа
        preview_crop : Разрешить обрезку превью.
        preview_size : Размер превью.
        type_resource : Фильтр по типу ресурсов, "file" или "dir"

        Returns
        -------
        Генератор по опубликованным ресурсам

        """

        params = args_asdict({"self": None, "type_resource": "type"})
        request = Request(self, "GET", "/v1/disk/resources/public", params)
        return PublicResourcesList(request)

    # @on_call_event
    def publish(self, path: str | ResourceShort, *, fields: str = None) -> Link:
        """
        Опубликовать ресурс
        Parameters
        ----------
        path : Путь к ресурсу
        fields :

        Returns
        -------

        """
        if isinstance(path, ResourceShort):
            path = path.path
        params = args_asdict({"self": None})
        request = Request(self, "PUT", "/v1/disk/public/resources/publish", params)
        return Link(request)

    # @on_call_event
    def unpublish(self, path: str | ResourceShort, *, fields: str = None) -> Link:
        """
        Отметить публикацию ресурса
        Parameters
        ----------
        path : Путь к ресурсу
        fields :

        Returns
        -------

        """
        if isinstance(path, ResourceShort):
            path = path.path

        params = args_asdict({"self": None})
        request = Request(self, "PUT", "/v1/disk/public/resources/unpublish", params)
        return Link(request)

    # @on_call_event
    def upload_file(
            self, path: str | ResourceShort, *, fields: str = None, overwrite: bool = None
    ) -> ResourceUploadLink:
        """
        Получить ссылку для загрузки файла
        Parameters
        ----------

        path : Путь к ресурсу
        fields :
        overwrite : Перезаписать существующий файл

        Returns
        -------

        """
        if isinstance(path, ResourceShort):
            path = path.path
        params = args_asdict({"self": None})
        request = Request(self, "GET", "/v1/disk/resources/upload", params)
        return ResourceUploadLink(request)

    # @on_call_event
    def upload_by_url(
            self,
            path: str | ResourceShort,
            url: href,
            *,
            disable_redirects: bool = None,
            fields: str = None,
    ) -> Link:
        """
        Загрузить файл в Диск по url
        Parameters
        ----------
        path : Путь к ресурсу
        url : URL внешнего ресурса, который следует загрузить.
        disable_redirects : Запретить делать редиректы
        fields :

        Returns
        -------
        Загрузка происходит асинхронно. Поэтому в ответ на запрос возвращается ссылка на асинхронную операцию.

        """
        if isinstance(path, ResourceShort):
            path = path.path

        params = args_asdict({"self": None})
        request = Request(self, "POST", "/v1/disk/resources/upload", params)
        return Link(request)

    # @on_call_event
    def info_public_resource(
            self,
            public_key: str,
            *,
            fields: FieldsList = None,
            limit: int = None,
            offset: int = None,
            path: str = None,
            preview_crop: bool = None,
            preview_size: str = None,
            sort: str = None,
    ) -> PublicResource:
        """
        Получить метаинформацию о публичном файле или каталоге

        Parameters
        ----------
        config :
        path : Путь к ресурсу
        fields : Список возвращаемых атрибутов
        limit : Количество выводимых вложенных ресурсов.
        offset : Смещение от начала списка вложенных ресурсов.
        preview_crop : Разрешить обрезку превью.
        preview_size : Размер превью.
        sort : Поле для сортировки вложенных ресурсов.

        Returns
        -------

        """

        params = args_asdict({"self": None})
        request = Request(self, "GET", "/v1/disk/public/resources", params)
        return PublicResource(request)

    # @on_call_event
    def savetodisk_public_resource(
            self,
            public_key: str,
            *,
            fields: str = None,
            name: str = None,
            path: str = None,
            save_path: str = None,
            force_async: bool = None,
    ) -> Link:
        """
        Сохранить публичный ресурс в папку Загрузки
        Parameters
        ----------
        public_key : Ключ или публичный URL ресурса.
        fields :
        name : Имя, под которым ресурс будет сохранён в папке
        path : Путь к копируемому ресурсу в публичной папке.
        save_path : Путь к папке, в которую будет сохранен ресурс. По умолчанию «Загрузки».

        Returns
        -------
        Если сохранение происходит асинхронно, то вернёт ответ с кодом 202 и ссылкой на асинхронную операцию.
        Иначе вернёт ответ с кодом 201 и ссылкой на созданный ресурс.

        """

        params = args_asdict({"self": None})
        request = Request(
            self, "POST", "/v1/disk/public/resources/save-to-disk", params
        )
        return Link(request)

    # @on_call_event
    def trash_restore(
            self,
            path: str | ResourceShort,
            fields: FieldsList = None,
            name: str = None,
            overwrite: bool = None,
            force_async: bool = None,
    ) -> Link:
        """
        Восстановить ресурс из корзины
        Parameters
        ----------
        path : Путь к ресурсу в корзине
        fields :
        name : Имя, под которым будет восстановлен ресурс.
        overwrite : Перезаписать существующий ресурс восстанавливаемым.

        Returns
        -------
        Если восстановление происходит асинхронно, то вернёт ответ с кодом 202 и ссылкой на асинхронную операцию.
        Иначе вернёт ответ с кодом 201 и ссылкой на созданный ресурс.
        """
        if isinstance(path, ResourceShort):
            path = path.path

        params = args_asdict({"self": None})
        request = Request(self, "PUT", "/v1/disk/trash/resources/restore", params)
        return Link(request)

    # @on_call_event
    def trash(
            self,
            path: str | ResourceShort = "/",
            fields: FieldsList = None,
            preview_crop: bool = None,
            preview_size: str = None,
            sort: str = None,
            limit: int = None,
            offset: int = None,
    ) -> TrashResource:
        """
        Получить содержимое корзины
        Parameters
        ----------
        path : Путь к ресурсу в корзине
        fields :
        preview_crop :
        preview_size :
        sort :

        Returns
        -------

        """
        if isinstance(path, ResourceShort):
            path = path.path

        params = args_asdict({"self": None})
        request = Request(self, "GET", "/v1/disk/trash/resources", params)
        return TrashResource(request)

    # @on_call_event
    def trash_clear(
            self,
            *,
            path: str = ResourceShort | None,
            fields: FieldsList = None,
            force_async: bool = None,
    ) -> Link:
        """
        Очистить корзину или только выбранный ресурс
        Если параметр path не задан или указывает на корень Корзины, то корзина будет полностью очищена,
        иначе из Корзины будет удалён только тот ресурс, на который указывает path

        Parameters
        ----------
        path : Путь к ресурсу в корзине
        fields :

        Returns
        -------
        Если удаление происходит асинхронно, то вернёт ответ со статусом 202 и ссылкой на асинхронную операцию.
        Иначе вернёт ответ со статусом 204 и пустым телом.
        """
        if isinstance(path, ResourceShort):
            path = path.path

        params = args_asdict({"self": None})
        request = Request(self, "DELETE", "/v1/disk/trash/resources", params)
        return Link(request)

    # @on_call_event
    def status_operation(
            self,
            operation_id: str,
            *,
            fields: FieldsList = None,
    ) -> str:
        """
        Получить статус асинхронной операции
        Parameters
        ----------
        operation_id : Идентификатор операции
        fields :

        Returns
        -------
        Статус операции
        """
        params = args_asdict({"self": None, "operation_id": None})
        request = Request(
            self, "GET", "/v1/disk/operations/" + operation_id, params=params
        )
        return request.response_body["status"]

    # @on_call_event
    def info(
            self,
            *,
            fields: str = None,
            preview_crop: bool = None,
            preview_size: str = None,
            sort: str = None,
    ) -> DiskInfo:
        """
        Получить метаинформацию о диске пользователя
        Parameters
        ----------
        fields : Список возвращаемых атрибутов
        preview_crop : Разрешить обрезку превью
        preview_size : Размер превью
        sort : Поле для сортировки вложенных ресурсов

        Returns
        -------

        """
        params = args_asdict({"self": None})
        request = Request(self, "GET", "/v1/disk/", params)
        return DiskInfo(request)

    # #@on_call_event
    def download_file(
            self,
            remote_pathname: str,
            local_pathname: str,
            progress_fn: typing.Callable[[int], None] = None,
            chunk_size: int = 8192,
    ):
        link = self.download_resource(path=remote_pathname)
        with requests.get(link.href, stream=True) as r:
            with open(local_pathname, "wb") as f:
                loaded_size = 0
                for chunk in r.iter_content(chunk_size=chunk_size):
                    f.write(chunk)
                    loaded_size += len(chunk)
                    if callable(progress_fn):
                        progress_fn(loaded_size)

    # #@on_call_event
    def upload(
            self,
            remote_pathname: str,
            local_pathname: str,
            overwrite: bool = False,
            progress_fn: typing.Callable[[int], None] = None,
            chunk_size: int = 8192,
    ):
        def none_if_false(value):
            return True if value is not None and value else None

        def get_chunks():
            total_read = 0
            with open(local_pathname, "rb") as f:
                while chunk := f.read(chunk_size):
                    total_read += len(chunk)
                    yield chunk
                    if callable(progress_fn):
                        progress_fn(total_read)

        link = self.upload_file(
            path=remote_pathname, overwrite=none_if_false(overwrite)
        )
        requests.put(link.href, data=get_chunks(), stream=True)
        return link.operation_id

    def remove(
            self,
            remote_pathname: str,
            permanently: bool = False,
            check_md5: str = None,
            force_async=False,
    ):
        def none_if_false(value):
            return True if value is not None and value else None

        link = self.remove_resource(
            path=remote_pathname,
            permanently=none_if_false(permanently),
            md5=none_if_false(check_md5),
            force_async=none_if_false(force_async),
        )
        if force_async and isinstance(link, Link):
            return link.operation_id
