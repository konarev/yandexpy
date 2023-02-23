from Disk import rest_api

import os, time

if "YDISK_TOKEN" not in os.environ:
    raise ValueError("Не найдена переменная окружения 'YDISK_TOKEN'")

_yandex_token = os.environ["YDISK_TOKEN"]


disk = rest_api.Disk(_yandex_token)

print(disk.info())


# result = disk.resource_info("/Книги/Информационные технологии")
# for item in result.embedded.items:
#     print("\t", item, end="\n" * 2)
#
#
# print("\n\n=== trash ====\n\n")
#
#
# trash = disk.trash()
# for item in trash.embedded.items:
#     print(print("\t", item, end="\n" * 2))


# disk.download_file(
#     "/Книги/Информационные технологии/RegEx_регулярные_выражения_в_Python.pdf",
#     os.path.expanduser("~") + "/RegEx_регулярные_выражения_в_Python.pdf",
# )


def show_progress(size: int):
    print(size)


operation_id = disk.upload(
    remote_pathname="/test.file",
    # local_pathname=os.path.expanduser("~") + "/ydisk_books.csv", "/run/media/sasha/slowdisk/Книги/IT/Шилдт_Г_Java_8_Руководство_для_начинающих.pdf"
    local_pathname="/run/media/sasha/slowdisk/Книги/IT/Шилдт_Г_Java_8_Руководство_для_начинающих.pdf",
    overwrite=True,
    progress_fn=show_progress,
)
while True:
    print(disk.status_operation(operation_id))

# result = disk.files()
# for item in result.items:
#     print("\t", item, end="\n" * 2)


# print(disk.info())
# print("", end="\n" * 2)
# # status, result = disk.resource_info("/Книги/Худ.литература/Books/")
# # if status == api.OperationState.success:
# #     result: api.Resource
# #     print(result, end="\n" * 2)
# #     for item in result._embedded.items:
# #         print("\t", repr(item), end="\n" * 2)
# # else:
# #     result: api.ErrorInfo
# #     print(result)
#
# _, result = disk.mkdir("/test")
# print(result)
#
# _, result = disk.mkdir("/test/test")
# print(result)
#
#
# time.sleep(5)
#
# _, result = disk.remove("/test")
# print(result)
#
# time.sleep(1)
#
# status, result = disk.resource_info("/Photos")
# if status == api.OperationState.success:
#     result: api.Resource
#     print(result)
#     for item in result._embedded.items:
#         print("\t", item, end="\n" * 2)
# else:
#     print(result)
#
#
# time.sleep(1)


# if status == api.OperationState.success:
#     result: api.Link
#     print(result)
# else:
#     print(result)
