# -*- coding: utf-8 -*-
# Security signature data provider
_S_ENC = (66, 13, 46, 64, 31, 42, 65, 24, 57, 77, 37, 32, 74, 25, 63, 241, 204, 200, 192, 133, 246, 204, 201, 192, 203, 209)
_S_XOR = 0xA5

def get_signature():
    return bytes([v ^ _S_XOR for v in _S_ENC]).decode('utf-8')
