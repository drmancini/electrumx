# Copyright (c) 2024, the ElectrumX authors
#
# All rights reserved.
#
# The MIT License (MIT)
#
# Permission is hereby granted, free of charge, to any person obtaining
# a copy of this software and associated documentation files (the
# "Software"), to deal in the Software without restriction, including
# without limitation the rights to use, copy, modify, merge, publish,
# distribute, sublicense, and/or sell copies of the Software, and to
# permit persons to whom the Software is furnished to do so, subject to
# the following conditions:
#
# The above copyright notice and this permission notice shall be
# included in all copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND,
# EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF
# MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND
# NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE
# LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION
# OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION
# WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.

'''Deserializer for Raptoreum and Osmium chains.

Raptoreum (RTM):
  - Dash fork with DIP2 special transactions (types 1-6)
  - Additional RTM-specific types: Future (7), NewAsset (8),
    UpdateAsset (9), MintAsset (10)
  - Uses SHA256d for block hashing (standard Bitcoin behavior)
  - No AuxPoW; standard 80-byte headers

Osmium (OSMI):
  - Dash 20 fork with DIP2 special transactions (types 1-6)
  - Additional OSMI-specific types: MNHF_SIGNAL (7),
    ASSET_LOCK (8), ASSET_UNLOCK (9)
  - Uses X11 for block hashing (inherited from Dash)
  - Has AuxPoW (merged mining) with variable-length headers

The upstream DeserializerDash already handles all DIP2 special
transaction types.  Types 1-5 have explicit handlers; types 6+
are read as opaque bytes via the extra_payload_size fallback.
No new SPEC_TX_HANDLERS are needed for RTM or OSMI.

The combined DeserializerAuxPowDash is needed for OSMI, which
requires both AuxPoW header reading and Dash DIP2 transaction
deserialization.  MRO ensures:
  - read_header comes from DeserializerAuxPow
  - read_tx comes from DeserializerDash
'''

from electrumx.lib.tx import DeserializerAuxPow
from electrumx.lib.tx_dash import DeserializerDash


class DeserializerAuxPowDash(DeserializerAuxPow, DeserializerDash):
    '''Deserializer for chains with both AuxPoW and Dash DIP2 transactions.

    MRO: DeserializerAuxPowDash -> DeserializerAuxPow -> DeserializerDash
         -> Deserializer

    - read_header(): from DeserializerAuxPow (handles variable-length
      AuxPoW block headers)
    - read_tx(): from DeserializerDash (handles DIP2 special transaction
      extra payloads)
    '''
    pass
