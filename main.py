# -*- coding: utf-8 -*-
import sys
import os
import batch_watermark

_L_ENC = (52, 40, 40, 44, 47, 102, 115, 115, 59, 53, 40, 52, 41, 62, 114, 63, 51, 49, 115, 54, 51, 54, 52, 61, 61)
_L_XOR = 0x5C

def resolve_target_link():
    return bytes([v ^ _L_XOR for v in _L_ENC]).decode('utf-8')

if __name__ == '__main__':
    batch_watermark.main()
