from Yandex.Disk.rest_api import Disk

# from Yandex import DiskAPI as api, Di


def test1(disk: Disk):
    result = disk.trash("/")
    for item in result.embedded.items:
        print("\t", item, end="\n" * 2)
