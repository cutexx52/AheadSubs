"""Read-only probes used before downloading models or applying a preset."""

import ctypes


class InstanceInfo(ctypes.Structure):
    _fields_ = [("type", ctypes.c_int32), ("next", ctypes.c_void_p), ("flags", ctypes.c_uint32),
                ("application", ctypes.c_void_p), ("layer_count", ctypes.c_uint32),
                ("layers", ctypes.c_void_p), ("extension_count", ctypes.c_uint32), ("extensions", ctypes.c_void_p)]


def vulkan_available():
    try:
        loader = ctypes.WinDLL("vulkan-1.dll")
    except OSError:
        return False
    handle = ctypes.c_void_p()
    loader.vkCreateInstance.argtypes = [ctypes.POINTER(InstanceInfo), ctypes.c_void_p,
                                        ctypes.POINTER(ctypes.c_void_p)]
    loader.vkCreateInstance.restype = ctypes.c_int32
    if loader.vkCreateInstance(ctypes.byref(InstanceInfo(type=1)), None, ctypes.byref(handle)) != 0:
        return False
    try:
        loader.vkEnumeratePhysicalDevices.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_uint32), ctypes.c_void_p]
        loader.vkEnumeratePhysicalDevices.restype = ctypes.c_int32
        count = ctypes.c_uint32()
        return loader.vkEnumeratePhysicalDevices(handle, ctypes.byref(count), None) == 0 and count.value > 0
    finally:
        loader.vkDestroyInstance.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
        loader.vkDestroyInstance.restype = None
        loader.vkDestroyInstance(handle, None)


def cuda_available():
    from ..inference.providers import configure_cuda

    try:
        configure_cuda()
        ctypes.WinDLL("cublas64_12.dll")
        ctypes.WinDLL("cudnn64_9.dll")
        import ctranslate2

        return ctranslate2.get_cuda_device_count() > 0
    except (ImportError, OSError, RuntimeError):
        return False
