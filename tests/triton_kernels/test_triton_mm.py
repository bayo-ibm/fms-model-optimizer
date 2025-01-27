# Copyright The FMS Model Optimizer Authors
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""Pytest configuration file with fixtures for triton kernel functionality test"""

# Third Party
import pytest
import torch

# Local
from fms_mo.custom_ext_kernels.triton_kernels import (
    tl_matmul_chunk_truncate as tl_matmul,
)
from fms_mo.modules.linear import LinearFPxAcc


@pytest.mark.parametrize("mkn", [64, 256, 1024, 4096])
@pytest.mark.parametrize(
    "dtype_to_test",
    [
        torch.float,
        torch.float16,
        torch.bfloat16,
        torch.float8_e4m3fn,
        torch.float8_e5m2,
    ],
)
def test_triton_matmul_fp(mkn, dtype_to_test):
    """Parametric tests for triton matmul kernel using variety of tensor sizes and dtypes."""
    torch.manual_seed(23)
    m = n = k = mkn
    a = torch.randn((m, k), device="cuda", dtype=torch.float)
    b = torch.randn((k, n), device="cuda", dtype=torch.float)

    torch_mm_device = "cuda"
    if dtype_to_test in [torch.float8_e4m3fn, torch.float8_e5m2]:
        cuda_cc = torch.cuda.get_device_capability()
        if cuda_cc[0] < 9 and cuda_cc != (8, 9):
            return
        else:
            # torch.matmul does not support fp8 x fp8 on cuda
            torch_mm_device = "cpu"

    a = a.to(dtype_to_test)
    b = b.to(dtype_to_test)
    torch_output = (
        torch.matmul(a.to(torch_mm_device), b.to(torch_mm_device))
        .to("cuda")
        .to(torch.float)
    )
    tl_output_no_trun = tl_matmul(a, b).to(torch.float)
    tl_output_trun_8b = tl_matmul(a, b, chunk_trun_bits=8).to(torch.float)

    diff_no_trun = torch_output - tl_output_no_trun
    diff_trun_8b = torch_output - tl_output_trun_8b

    assert torch.norm(diff_no_trun) / torch.norm(torch_output) < 1e-5
    assert torch.norm(diff_trun_8b) / torch.norm(torch_output) < 1e-3


@pytest.mark.parametrize("mkn", [64, 256, 1024, 4096])
def test_triton_matmul_int8(mkn):
    """Parametric tests for triton imatmul kernel using variety of tensor sizes."""
    torch.manual_seed(23)
    m = n = k = mkn
    a = torch.randint(-128, 127, (m, k), device="cuda", dtype=torch.int8)
    b = torch.randint(-128, 127, (k, n), device="cuda", dtype=torch.int8)

    torch_output = torch.matmul(a.to(torch.float), b.to(torch.float))
    # cast tl_matmul results to float because torch.norm only supports float
    tl_output_no_trun = tl_matmul(a, b).to(torch.float)
    tl_output_trun_8b = tl_matmul(a, b, chunk_trun_bits=8).to(torch.float)

    diff_no_trun = torch_output - tl_output_no_trun
    diff_trun_8b = torch_output - tl_output_trun_8b

    assert torch.norm(diff_no_trun) / torch.norm(torch_output) < 1e-5
    assert torch.norm(diff_trun_8b) / torch.norm(torch_output) < 1e-2


@pytest.mark.parametrize("feat_in_out", [(64, 128), (256, 1024), (1024, 4096)])
@pytest.mark.parametrize("trun_bits", [0, 8, 12, 16])
def test_linear_fpx_acc(feat_in_out, trun_bits):
    """Parametric tests for LinearFPxAcc. This Linear utilizes triton kernel hence can only be run
    on CUDA.
    """

    torch.manual_seed(23)
    feat_in, feat_out = feat_in_out
    lin = torch.nn.Linear(feat_in, feat_out, device="cuda")
    lin_fpx = LinearFPxAcc.from_nn(lin, trun_bits=trun_bits)
    inputs = torch.randn((512, feat_in), device="cuda")

    with torch.no_grad():
        baseline = lin(inputs)
        diff = lin_fpx(inputs) - baseline
        rel_err = torch.norm(diff) / torch.norm(baseline)

    rel_tol = 1e-2 if trun_bits > 10 else 1e-4
    assert rel_err < rel_tol
