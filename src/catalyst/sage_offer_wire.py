"""Exact, dependency-light validation for Sage's serialized Chia Offer wire format.

The Bech32m algorithm below is adapted from Pieter Wuille's reference
implementation (Copyright (c) 2017 Pieter Wuille, MIT License).

The versioned puzzle compression dictionary is copied from
chia-blockchain 2.5.7's chia.wallet.util.puzzle_compression module
(Copyright Chia Network Inc. and contributors, Apache License 2.0). It is
stored as base64 solely to keep this module text-only. CATalyst's changes are
limited to decoding the cumulative version-6 bytes and enforcing stricter
bounded/canonical stream handling before the chia_rs parser.

Upstream sources:
- https://github.com/sipa/bech32/tree/bip-bech32m
- https://github.com/Chia-Network/chia-blockchain/tree/2.5.7

Complete upstream license texts are retained in
``licenses/Pieter-Wuille-bech32-MIT.txt`` and
``licenses/Chia-Network-chia-blockchain-Apache-2.0.txt`` and are bundled with
CATalyst releases. See ``THIRD_PARTY_NOTICES.md`` for exact modifications.
"""

from __future__ import annotations

import base64
from collections.abc import Iterable
import hashlib
from typing import Any
import zlib


_CHARSET = "qpzry9x8gf2tvdw0s3jn54khce6mua7l"
_BECH32M_CONSTANT = 0x2BC830A3
_MAX_ENCODED_OFFER_LENGTH = 4 * 1024 * 1024
_MAX_DECOMPRESSED_OFFER_LENGTH = 6 * 1024 * 1024
_DICTIONARY_ENDS = (0, 1647, 1914, 5862, 7534, 7827, 7827)
_DICTIONARY_SHA256 = "7c2632368f37f21a33b179c9bfd07c383d23c12fb48b47a9b24fa5029f8690a1"
_DICTIONARY_BASE64 = (
    "/wL//wH/Av//A/8L//8B/wL//wP//wn/Bf//Hf8L//8e//8L/wv//wL/Bv//BP8C//8E/xf/gICAgICAgID//wH/"
    "Av8X/y+A//8B/wiAgP8BgP//Af8E//8E/wT//wT/Bf//BP//Av8G//8E/wL//wT/F/+AgICA/4CAgID//wL/F/8v"
    "gICA/wGA//8E//8B/zL/Av//A///B/8FgP//Af8L//8BAv//Av8G//8E/wL//wT/Cf+AgICA//8C/wb//wT/Av//"
    "BP8N/4CAgICA//8B/wv//wEB/wWAgP8BgP8BgID/Av//Af8C/17//wT/Av//BP//BP8F//8E//8L/yz/BYD//wT/"
    "C/+AgICA//8E//8C/xf/L4D//wT/X///BP//Av8u//8E/wL//wT/F/+AgICA//8E//8L/4ICf/+CBX//ggt/gP//"
    "BP+Bv///BP+CAX///wT/ggL///8E/4IF////BP+CC///gICAgICAgICAgICAgP//BP//Af////+Byj3/Rv8CM///"
    "PAT/Af8Bgcv///8C/wL//wP/Bf//Af8C/zL//wT/Av//BP8N//8E//8L/yL//wv/LP80gP//C/8i//8L/yL//wv/"
    "LP9cgP8JgP//C/8i/wv//wv/LP+AgICAgP+AgICAgP//AQuA/wGA//8C//8D/wv//wH/Av//A///Cf//Av8u//8E"
    "/wL//wT/E/+AgICA/4ILn4D//wH/Av8m//8E/wL//wT//wL/E///BP9f//8E/xf//wT/L///BP+Bv///BP+CAX//"
    "/wT/G/+AgICAgICAgP//BP+CAX//gICAgID//wH/CICA/wGA//8B/wL//wP/F///Af8C//8D//8g/4G/gP//AYIB"
    "f///Af8IgID/AYD//wH/CICA/wGAgP8BgP//BP//BP8F/yeA//8E//8Q/wv/V4D/d4CA/wL//wP/Bf//Af8C//8D"
    "//8J//8C//8D//8J/xH/eID//wFZ/4CA/wGA//8BgY+A//8B/wL/ev//BP8C//8E/w3//wT/C///BP//BP+Buf+C"
    "AXmA/4CAgICAgP//Af8C/1r//wT/Av//BP//Av//A///Cf8R/3iA//8B/wT/eP//BP//Av82//8E/wL//wT/E///"
    "BP8p//8E//8L/yz/W4D//wT/K/+AgICAgICA/zmAgP//Af8C//8D//8J/xH/JID//wH/BP8k//8E//8L/yD/KYD/"
    "OYCA//8BCYD/AYCA/wGA//8E//8C//8D//8J/xH/eID//wFZ/4CA/wGA//8E//8C/3r//wT/Av//BP8N//8E/wv/"
    "/wT/F/+AgICAgID/gICAgICAgP8BgP//Af8E/4D//wT/gP8XgICA/wGA////Av//A/8F//8B/wT/Cf//Av8m//8E"
    "/wL//wT/Df//BP8L/4CAgICAgP//AQuA/wGA/wv/Iv//C/8s/1iA//8L/yL//wv/Iv//C/8s/1yA/wWA//8L/yL/"
    "/wL/Mv//BP8C//8E/wf//wT//wv/LP8sgP+AgICAgP//C/8s/4CAgICA//8C//8D//8H/wWA//8B/wv//wEC//8C"
    "/y7//wT/Av//BP8J/4CAgID//wL/Lv//BP8C//8E/w3/gICAgID//wH/C/8s/wWAgP8BgP//BP//BP8o//8E/1//"
    "gICA//8C/37//wT/Av//BP//BP//BP8v/wWA//8E/1//ggF/gID//wT//wL/ev//BP8C//8E/wv//wT/Bf//Af+A"
    "gICAgID//wT/F///BP+Bv///BP+CAX///wT//wv/ggT///8C/zb//wT/Av//BP8J//8E/4IK////BP//C/8s/y2A"
    "//8E/xX/gICAgICAgP+CFv+A//8E/4IF////BP+CC///gICAgICAgICAgICA/wL/Kv//BP8C//8E/1///wT/O///"
    "BP//Av//A/8X//8B/wn/Lf//C/8n//8C/zb//wT/Av//BP8p//8E/1f//wT//wv/LP+BuYD//wT/Wf+AgICAgICA"
    "/4G3gID/gID/AYD//wT/F///BP8F//8E/4IC////BP//BP//BP8k//8E//8L/3z/L/+CAX+A/4CAgP//BP//BP8w"
    "//8E//8L/4G///8L/3z/Ff//EP+CAX///xH/ggLf/yuA/4IC/4CAgP+AgID/E4CA/4CAgICAgICAgID/AYCA/wL/"
    "/wH/Av8K//8E/wL//wT/A/+AgICA//8E//8B//8zPv//Av//A/8F//8B/wT//wT/DP//BP//Av8e//8E/wL//wT/"
    "Cf+AgICA/4CAgP//Av8W//8E/wL//wT/Gf//BP//Av8K//8E/wL//wT/Df+AgICA/4CAgICAgP+AgP8BgP//Av//"
    "A/8F//8B/wT//wT/CP8JgP//Av8W//8E/wL//wT/Df//BP8L/4CAgICAgP//AQuA/wGA/wL//wP//wf/BYD//wH/"
    "C///AQL//wL/Hv//BP8C//8E/wn/gICAgP//Av8e//8E/wL//wT/Df+AgICAgP//Af8L//8BAf8FgID/AYD/AYCA"
    "/wL//wH/Av//A///GP8v/zSA//8B/wT//wT/IP//BP8v/4CAgP//BP//Av8+//8E/wL//wT/Bf//BP//Av8q//8E"
    "/wL//wT/J///BP//Av//A/93//8B/wL/Nv//BP8C//8E/wn//wT/V///BP//Av8u//8E/wL//wT/Bf+AgICA/4CA"
    "gICAgP//AR2A/wGA//8E//8C//8D/3f//wGBt///AVeA/wGA/4CAgICAgP//BP93/4CAgICAgP//Av86//8E/wL/"
    "/wT/Bf//BP//Av8L/1+A//8B/4CAgICAgICA//8B/wiAgP8BgP//BP//Af////9JR/8CM///BAH/AQL///8g/wL/"
    "/wP/Bf//Af8C/zL//wT/Av//BP8N//8E//8L/zz//wv/NP8kgP//C/88//8L/zz//wv/NP8sgP8JgP//C/88/wv/"
    "/wv/NP+AgICAgP+AgICAgP//AQuA/wGA//8C//8D//8i//8J//8N/wWA/yKA//8J//8N/wuA/yKA//8V/xf//wGB"
    "/4CA//8B/wv/Bf8L/xeA//8B/wiAgP8BgP8C//8D/wv//wH/Av//A///Av8m//8E/wL//wT/E/+AgICA//8B/wL/"
    "/wP//yD/F4D//wH/Av//A///Cf+Bs///AYGPgP//Af8C/zr//wT/Av//BP8F//8E/xv//wT/NP+AgICAgID//wH/"
    "BP//BP8j//8E//8C/zb//wT/Av//BP8J//8E/1P//wT//wL/Lv//BP8C//8E/wX/gICAgP+AgICAgID/c4CA//8C"
    "/zr//wT/Av//BP8F//8E/xv//wT/NP+AgICAgICAgP8BgP//Af8IgID/AYD//wH/BP8T//8C/zr//wT/Av//BP8F"
    "//8E/xv//wT/F/+AgICAgICAgP8BgP//Af8C//8D/xf/gP//Af8IgID/AYCA/wGA////Av//A///Cf8J/ziA//8B"
    "/wL//wP//xj/Lf//AQGA//8B/wEB/4CA/wGA/4CA/wGA/wv/PP//C/80/yiA//8L/zz//wv/PP//C/80/yyA/wWA"
    "//8L/zz//wL/Mv//BP8C//8E/wf//wT//wv/NP80gP+AgICAgP//C/80/4CAgICA//8C//8D//8H/wWA//8B/wv/"
    "/wEC//8C/y7//wT/Av//BP8J/4CAgID//wL/Lv//BP8C//8E/w3/gICAgID//wH/C///AQH/BYCA/wGA/wL//wP/"
    "/yH/F///Cf8L/xWAgP//Af8E/zD//wT/C/+AgID//wH/CICA/wGA/wGAgP8C//8B/wL/Pv//BP8C//8E/wX//wT/"
    "/wL/L/9fgP//BP+A//8E//8E//8E/wv//wT/F/+AgID//wH/gICA//8B/4CAgICAgICA//8E//8B////AjP/BP8B"
    "Af//Av8C//8D/wX//wH/Av8a//8E/wL//wT/Df//BP//C/8S//8L/yz/FID//wv/Ev//C/8S//8L/yz/PID/CYD/"
    "/wv/Ev8L//8L/yz/gICAgID/gICAgID//wELgP8BgP//C/8S//8L/yz/EID//wv/Ev//C/8S//8L/yz/PID/BYD/"
    "/wv/Ev//Av8a//8E/wL//wT/B///BP//C/8s/yyA/4CAgICA//8L/yz/gICAgID//wL//wP//wf/BYD//wH/C///"
    "AQL//wL/Lv//BP8C//8E/wn/gICAgP//Av8u//8E/wL//wT/Df+AgICAgP//Af8L//8BAf8FgID/AYD/Av//A/8L"
    "//8B/wL//wP//wn/I/8YgP//Af8C//8D//8Y/4Gz/yyA//8B/wL//wP//yD/F4D//wH/Av8+//8E/wL//wT/Bf//"
    "BP8b//8E/zP//wT/L///BP9f/4CAgICAgICA//8B/wiAgP8BgP//Af8E/xP//wL/Pv//BP8C//8E/wX//wT/G///"
    "BP8X//8E/y///wT/X/+AgICAgICAgICA/wGA//8B/wL//wP//wn/I///AYHogP//Af8C/z7//wT/Av//BP8F//8E"
    "/xv//wT/F///BP//Av//A///Iv//Cf//Av8u//8E/wL//wT/U/+AgICA/4IBT4D//yD/X4CA//8B/wL/U///BP+B"
    "j///BP+CAU///wT/gbP/gICAgID//wH/CICA/wGA//8E/yz/gICAgICAgID//wH/BP8T//8C/z7//wT/Av//BP8F"
    "//8E/xv//wT/F///BP8v//8E/1//gICAgICAgICAgP8BgID/AYD//wH/BP//BP8Y//8E//8C/xb//wT/Av//BP8F"
    "//8E/yf//wT//wv/LP+CAU+A//8E//8C/y7//wT/Av//BP+Bj/+AgICA//8E//8L/yz/BYD/gICAgICAgID/N4CA"
    "/4GvgID/AYD/AYCA/wL//wH/Av8m//8E/wL//wT/Bf//BP8X//8E/wv//wT//wL/L/9fgP+AgICAgICA//8E//8B"
    "////gq1M/wIz//8+BP+B9gH///8BAv//Av//A/8F//8B/wL/Kv//BP8C//8E/w3//wT//wv/Mv//C/88/zSA//8L"
    "/zL//wv/Mv//C/88/yKA/wmA//8L/zL/C///C/88/4CAgICA/4CAgICA//8BC4D/AYD/BP//BP84//8E//8C/zb/"
    "/wT/Av//BP8F//8E/yf//wT//wL/Lv//BP8C//8E//8C//8D/4Gv//8Bga///wELgP8BgP+AgICA//8E//8L/zz/"
    "T4D//wT//wv/PP8FgP+AgICAgICAgP83gID/ggFvgP///wL/Pv//BP8C//8E/wX//wT/C///BP8X//8E/y///wT/"
    "L///Af+A/4CAgICAgICAgP8L/zL//wv/PP8ogP//C/8y//8L/zL//wv/PP8igP8FgP//C/8y//8C/yr//wT/Av//"
    "BP8H//8E//8L/zz/PID/gICAgID//wv/PP+AgICAgP//Av//A///B/8FgP//Af8L//8BAv//Av8u//8E/wL//wT/"
    "Cf+AgICA//8C/y7//wT/Av//BP8N/4CAgICA//8B/wv//wEB/wWAgP8BgP8C//8D/1///wH/Av//A///Cf+CAR//"
    "OID//wH/Av//A///Cf//GP+CBZ+A/zyA//8B/wL//wP//yD/gb+A//8B/wL/Pv//BP8C//8E/wX//wT/C///BP8X"
    "//8E/y///wT/gd///wT/ggGf//8E/4IBf/+AgICAgICAgICA//8B/wiAgP8BgP//Af8E/4Gf//8C/z7//wT/Av//"
    "BP8F//8E/wv//wT/F///BP8v//8E/4Hf//8E/4G///8E/4IBf/+AgICAgICAgICAgID/AYD//wH/Av//A///Cf+C"
    "AR//LID//wH/Av//A///IP+CAX+A//8B/wT//wT/JP//BP//Dv8Q//8C/y7//wT/Av//BP+CAZ//gICAgID/gICA"
    "//8C/z7//wT/Av//BP8F//8E/wv//wT/F///BP8v//8E/4Hf//8E/4G///8E//8C/wv//wT/F///BP8v//8E/4IB"
    "n/+AgICAgP+AgICAgICAgICAgP//Af8IgID/AYD//wH/Av//A///Cf+CAR//JID//wH/Av//A///IP//Av//A///"
    "Cf//ASL//w3/ggKfgID//wH/Av//A///Cf//DP+CAp//gP//AQKA/xCA//8B/wEB/4CA/wGA/4CA/wGAgP//Af8E"
    "/4Gf//8C/z7//wT/Av//BP8F//8E/wv//wT/F///BP8v//8E/4Hf//8E/4G///8E/4IBf/+AgICAgICAgICAgP//"
    "Af8IgID/AYD//wH/BP+Bn///Av8+//8E/wL//wT/Bf//BP8L//8E/xf//wT/L///BP+B3///BP+Bv///BP+CAX//"
    "gICAgICAgICAgICA/wGAgP8BgID/AYD//wH/Av86//8E/wL//wT/Bf//BP8L//8E/4G///8E//8C//8D/4IBf///"
    "AYIBf///Af8C/wv//wT/F///BP8v//8B/4CAgICAgP8BgP+AgICAgICAgP8BgP8BgID/Av//Af8E//8E//8C//8D"
    "//8i/yf/N4D//wH/Av//A///If//Cf8n//8Bgm11gP//Cf8n//8Bgmx1gP//Cf8n//8BdYCA//8B/wL/Av//BP8C"
    "//8E/wX//wT/J///BP83/4CAgICAgP//AQWA/wGA//8BBYD/AYD//wT/C/+AgID//wH/gICA//8E//8B/wL//wP/"
    "Bf//Af8C//8D//8J/xH/C4D//wH/BP//BP8L//8E/xf/GYCA/w2A//8B/wT/Cf//Av8C//8E/wL//wT/Df//BP8L"
    "//8E/xf/gICAgICAgID/AYD/gID/AYD/AYCA/wL//wH/Av//A/+Bv///Af8E/4IBP///BP+A//8E//8C//8D//8i"
    "/4IBP///IP//Cf+CAT//L4CAgP//Af8E//8E/xD//wT//wv//wL/Lv//BP8C//8E/wn//wT/ggW///8E//8C/z7/"
    "/wT/Av//BP//BP8J//8E/4IBP/8dgID/gICAgP+AgICAgID/FYD/gICA//8C/xb//wT/Av//BP8L//8E/xf//wT/"
    "ggK///8E/xX/gICAgICAgID//wH/Av8W//8E/wL//wT/C///BP8X//8E/4ICv///BP8V/4CAgICAgICA/wGA/4CA"
    "gID//wH/BP8v//8B/4D/gICAgP8BgP//BP//Af///z8C/wT/AQH//4InEP8C/wL//wP/Bf//Af8C/zr//wT/Av//"
    "BP8N//8E//8L/yr//wv/LP8UgP//C/8q//8L/yr//wv/LP88gP8JgP//C/8q/wv//wv/LP+AgICAgP+AgICAgP//"
    "AQuA/wGA//8C//8D/xf//wH/BP//BP8Q//8E//8L/4Gn//8C/z7//wT/Av//BP//BP8v//8E//8E/wX//wT//wX/"
    "/xT//xL/R/8LgP8SgID//wT//wT/Bf+AgP+AgICA/4CAgP+AgICAgP+AgID//wL/Fv//BP8C//8E/wX//wT/C///"
    "BP83//8E/y//gICAgICAgID/gID/AYD//wv/Kv//C/8s/xiA//8L/yr//wv/Kv//C/8s/zyA/wWA//8L/yr//wL/"
    "Ov//BP8C//8E/wf//wT//wv/LP8sgP+AgICAgP//C/8s/4CAgICA/wL//wP//wf/BYD//wH/C///AQL//wL/Pv//"
    "BP8C//8E/wn/gICAgP//Av8+//8E/wL//wT/Df+AgICAgP//Af8L//8BAf8FgID/AYD/AYCA/wL//wH/Av9e//8E"
    "/wL//wT//wT/Bf//BP//C/80/wWA//8E/wv/gICAgP//BP//Av8X/y+A//8E/1///wT//wL/Lv//BP8C//8E/xf/"
    "gICAgP//BP//Av8q//8E/wL//wT/ggJ///8E/4IFf///BP+CC3//gICAgICA//8E/4G///8E/4IBf///BP+CAv//"
    "/wT/ggX///8E/4IL//+AgICAgICAgICAgICA//8E//8B/////z1G/wL/Mzz//wQB/wH/gcsC////IP8C//8D/wX/"
    "/wH/Av8y//8E/wL//wT/Df//BP//C/98//8L/zT/JID//wv/fP//C/98//8L/zT/LID/CYD//wv/fP8L//8L/zT/"
    "gICAgID/gICAgID//wELgP8BgP//Av//A///Iv//Cf//Df8FgP8igP//Cf//Df8LgP8igP//Ff8X//8Bgf+AgP//"
    "Af8L/wX/C/8XgP//Af8IgID/AYD//wL//wP/C///Af8C//8D//8J//8C/y7//wT/Av//BP8T/4CAgID/ggufgP//"
    "Af8C/1b//wT/Av//BP//Av8T//8E/1///wT/F///BP8v//8E/4G///8E/4IBf///BP8b/4CAgICAgICA//8E/4IB"
    "f/+AgICAgP//Af8IgID/AYD//wH/Av//A/8X//8B/wL//wP//yD/gb+A//8BggF///8B/wiAgP8BgP//Af8IgID/"
    "AYCA/wGA/wT//wT/Bf8ngP//BP//EP8L/1eA/3eAgP///wL//wP/Bf//Af8C//8D//8J//8C//8D//8J/xH/WID/"
    "/wFZ/4CA/wGA//8BgY+A//8B/wL/Jv//BP8C//8E/w3//wT/C///BP//BP+Buf+CAXmA/4CAgICAgP//Af8C/3r/"
    "/wT/Av//BP//Av//A///Cf8R/1iA//8B/wT/WP//BP//Av92//8E/wL//wT/E///BP8p//8E//8L/zT/W4D//wT/"
    "K/+AgICAgICA/zmAgP//Af8C//8D//8J/xH/eID//wH/Av//A///IP//Av//A///Cf//ASH//w3/KYCA//8B/wL/"
    "/wP//wn//wz/Kf+A/zSA/1yA//8B/wEB/4CA/wGA/4CA/wGAgP//AQn//wH/CICA/wGA//8BCYD/AYCA/wGA//8E"
    "//8C//8D//8J/xH/WID//wFZ/4CA/wGA//8E//8C/yb//wT/Av//BP8N//8E/wv//wT/F/+AgICAgID/gICAgICA"
    "gP8BgP//Af8E/4D//wT/gP8XgICA/wGA//8C//8D/wX//wH/BP8J//8C/1b//wT/Av//BP8N//8E/wv/gICAgICA"
    "//8BC4D/AYD/C/98//8L/zT/KID//wv/fP//C/98//8L/zT/LID/BYD//wv/fP//Av8y//8E/wL//wT/B///BP//"
    "C/80/zSA/4CAgICA//8L/zT/gICAgID//wL//wP//wf/BYD//wH/C///AQL//wL/Lv//BP8C//8E/wn/gICAgP//"
    "Av8u//8E/wL//wT/Df+AgICAgP//Af8L//8BAf8FgID/AYD//wT//wT/MP//BP9f/4CAgP//Av9+//8E/wL//wT/"
    "/wT//wT/L/8FgP//BP9f/4IBf4CA//8E//8C/yb//wT/Av//BP8L//8E/wX//wH/gICAgICA//8E/xf//wT/gb//"
    "/wT/ggF///8E//8C/yr//wT/Av//BP+CBP///wT//wL/dv//BP8C//8E/wn//wT/ggr///8E//8L/zT/LYD//wT/"
    "Ff+AgICAgICA//8E/4IW//+AgICAgID//wT/ggX///8E/4IL//+AgICAgICAgICAgID/Av9a//8E/wL//wT/X///"
    "BP87//8E//8C//8D/xf//wH/Cf8t//8C/yr//wT/Av//BP8n//8E//8C/3b//wT/Av//BP8p//8E/1f//wT//wv/"
    "NP+BuYD//wT/Wf+AgICAgICA//8E/4G3/4CAgICAgID/gID/AYD//wT/F///BP8F//8E/4IC////BP//BP//BP94"
    "//8E//8O/1z//wL/Lv//BP8C//8E//8E/y///wT/ggF//4CAgP+AgICAgP+AgID//wT//wT/IP//BP//C/+Bv/9c"
    "//8C/y7//wT/Av//BP//BP8V//8E//8Q/4IBf///Ef+CAt//K4D/ggL/gP+AgID/gICAgID/gICA/xOAgP+AgICA"
    "gICAgICA/wGAgP8C//8B/wL/Cv//BP8C//8E/wP/gICAgP//BP//Af//Mz7//wL//wP/Bf//Af8E//8E/wz//wT/"
    "/wL/Hv//BP8C//8E/wn/gICAgP+AgID//wL/Fv//BP8C//8E/xn//wT//wL/Cv//BP8C//8E/w3/gICAgP+AgICA"
    "gID/gID/AYD//wL//wP/Bf//Af8C//8D//8V/yn/gID//wH/BP//BP8I/wmA//8C/xb//wT/Av//BP8N//8E/wv/"
    "gICAgICA//8B/wiAgP8BgP//AQuA/wGA/wL//wP//wf/BYD//wH/C///AQL//wL/Hv//BP8C//8E/wn/gICAgP//"
    "Av8e//8E/wL//wT/Df+AgICAgP//Af8L//8BAf8FgID/AYD/AYCA"
)


def _puzzle_dictionary(version: int) -> bytes:
    if type(version) is not int or not 0 <= version < len(_DICTIONARY_ENDS):
        raise ValueError("unsupported Sage Offer compression version")
    dictionary = base64.b64decode(_DICTIONARY_BASE64, validate=True)
    if (
        len(dictionary) != _DICTIONARY_ENDS[-1]
        or hashlib.sha256(dictionary).hexdigest() != _DICTIONARY_SHA256
    ):
        raise ValueError("embedded Sage Offer compression dictionary is corrupt")
    return dictionary[: _DICTIONARY_ENDS[version]]


def _bech32_polymod(values: Iterable[int]) -> int:
    generators = (0x3B6A57B2, 0x26508E6D, 0x1EA119FA, 0x3D4233DD, 0x2A1462B3)
    checksum = 1
    for value in values:
        top = checksum >> 25
        checksum = ((checksum & 0x1FFFFFF) << 5) ^ value
        for index, generator in enumerate(generators):
            if (top >> index) & 1:
                checksum ^= generator
    return checksum


def _bech32_hrp_expand(hrp: str) -> list[int]:
    return (
        [ord(character) >> 5 for character in hrp]
        + [0]
        + [ord(character) & 31 for character in hrp]
    )


def _decode_offer_bech32(value: str) -> bytes:
    if (
        not value
        or value != value.lower()
        or any(ord(character) < 33 or ord(character) > 126 for character in value)
    ):
        raise ValueError("Sage Offer text is not canonical lowercase Bech32m")
    separator = value.rfind("1")
    if separator < 1 or separator + 7 > len(value):
        raise ValueError("Sage Offer text has an invalid Bech32m separator")
    hrp = value[:separator]
    if hrp != "offer":
        raise ValueError("Sage Offer text has an unexpected HRP")
    encoded = value[separator + 1 :]
    if any(character not in _CHARSET for character in encoded):
        raise ValueError("Sage Offer text has an invalid Bech32m character")
    data_with_checksum = [_CHARSET.index(character) for character in encoded]
    if (
        _bech32_polymod(_bech32_hrp_expand(hrp) + data_with_checksum)
        != _BECH32M_CONSTANT
    ):
        raise ValueError("Sage Offer text has an invalid Bech32m checksum")
    return bytes(_convertbits(data_with_checksum[:-6], 5, 8, pad=False))


def _encode_offer_bech32(value: bytes) -> str:
    data = _convertbits(value, 8, 5, pad=True)
    checksum_value = (
        _bech32_polymod(_bech32_hrp_expand("offer") + data + [0] * 6)
        ^ _BECH32M_CONSTANT
    )
    checksum = [(checksum_value >> (5 * (5 - index))) & 31 for index in range(6)]
    return "offer1" + "".join(_CHARSET[item] for item in data + checksum)


def _convertbits(
    data: Iterable[int],
    from_bits: int,
    to_bits: int,
    *,
    pad: bool,
) -> list[int]:
    accumulator = 0
    bit_count = 0
    converted: list[int] = []
    maximum_value = (1 << to_bits) - 1
    maximum_accumulator = (1 << (from_bits + to_bits - 1)) - 1
    for value in data:
        if value < 0 or value >> from_bits:
            raise ValueError("invalid Bech32m data value")
        accumulator = ((accumulator << from_bits) | value) & maximum_accumulator
        bit_count += from_bits
        while bit_count >= to_bits:
            bit_count -= to_bits
            converted.append((accumulator >> bit_count) & maximum_value)
    if pad:
        if bit_count:
            converted.append((accumulator << (to_bits - bit_count)) & maximum_value)
    elif bit_count >= from_bits or (
        (accumulator << (to_bits - bit_count)) & maximum_value
    ):
        raise ValueError("non-canonical Bech32m padding")
    return converted


def _decompress_offer(encoded_offer: bytes) -> bytes:
    if len(encoded_offer) < 3:
        raise ValueError("Sage Offer compression stream is truncated")
    version = int.from_bytes(encoded_offer[:2], "big")
    dictionary = _puzzle_dictionary(version)
    decompressor = zlib.decompressobj(zdict=dictionary)
    decoded = decompressor.decompress(
        encoded_offer[2:],
        _MAX_DECOMPRESSED_OFFER_LENGTH + 1,
    )
    if len(decoded) > _MAX_DECOMPRESSED_OFFER_LENGTH:
        raise ValueError("Sage Offer decompressed size exceeds the limit")
    if not decompressor.eof or decompressor.unconsumed_tail or decompressor.unused_data:
        raise ValueError("Sage Offer compression stream is incomplete or non-canonical")
    if decompressor.flush():
        raise ValueError("Sage Offer compression stream has deferred output")
    return decoded


def canonical_sage_offer_text(value: Any) -> str | None:
    """Return an exact Sage Offer string only when its full wire payload parses."""

    if (
        type(value) is not str
        or not value.startswith("offer1")
        or value != value.strip()
        or len(value) > _MAX_ENCODED_OFFER_LENGTH
    ):
        return None
    try:
        decoded = _decompress_offer(_decode_offer_bech32(value))
        from chia_rs import SpendBundle

        parsed = SpendBundle.from_bytes(decoded)
        if bytes(parsed) != decoded:
            return None
    except Exception:
        return None
    return value


def unsigned_sage_offer_text(value: Any) -> str | None:
    """Remove only a canonical Offer's signature for same-wallet taking.

    Sage signs every locally owned spend when taking an offer. If maker and taker
    are the same wallet, retaining the maker signature makes Sage aggregate that
    signature twice. This preserves the exact coin-spend bytes and compression
    version while replacing only the aggregate signature with the BLS identity.
    Invalid or non-canonical input fails closed.
    """

    if canonical_sage_offer_text(value) is None:
        return None
    try:
        encoded = _decode_offer_bech32(value)
        version = int.from_bytes(encoded[:2], "big")
        from chia_rs import G2Element, SpendBundle

        parsed = SpendBundle.from_bytes(_decompress_offer(encoded))
        unsigned = SpendBundle(parsed.coin_spends, G2Element())
        compressor = zlib.compressobj(zdict=_puzzle_dictionary(version))
        compressed = (
            version.to_bytes(2, "big")
            + compressor.compress(bytes(unsigned))
            + compressor.flush()
        )
        result = _encode_offer_bech32(compressed)
    except Exception:
        return None
    if len(result) > _MAX_ENCODED_OFFER_LENGTH:
        return None
    return result if canonical_sage_offer_text(result) == result else None
