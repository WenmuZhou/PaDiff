# Copyright (c) 2022 PaddlePaddle Authors. All Rights Reserved.
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

from .trainer_utils import report_guard, register_paddle_hooker, register_torch_hooker
from ..utils import (
    log,
    max_diff,
    tensors_mean,
)
from ..weights import remove_inplace, assign_weight


class Runner(object):
    def __init__(self, layer, module, loss_fn, layer_map, options):
        # self.paddle_device = paddle.get_device()
        # self.torch_device = next(module.parameters()).device

        self.layer = layer  # paddle layer
        self.module = module  # torch module
        self.options = options

        if options["use_loss"]:
            self.paddle_loss = loss_fn[0]
            self.torch_loss = loss_fn[1]

        # layer_map should be part of the module
        self.layer_map = layer_map

        remove_inplace(self.layer, self.module)

        self.paddle_rep = None
        self.torch_rep = None

    def assign_weight_(self):
        return assign_weight(self.layer, self.module, self.layer_map)

    def set_report(self, paddle_rep, torch_rep):
        paddle_rep.layer_map = self.layer_map
        torch_rep.layer_map = self.layer_map
        self.paddle_rep = paddle_rep
        self.torch_rep = torch_rep

    def forward_step(self, example_inp):
        paddle_input, torch_input = example_inp
        with report_guard(self.torch_rep, self.paddle_rep):
            with register_torch_hooker(self.module, self.layer_map):
                try:
                    torch_output = self.module(**torch_input)
                    if self.options["use_loss"]:
                        loss = self.torch_loss(torch_output)
                        self.torch_rep.set_loss(loss)
                    else:
                        loss = tensors_mean(torch_output, "torch")
                    if self.options["diff_phase"] == "both" or self.options["diff_phase"] == "backward":
                        loss.backward()
                except Exception as e:
                    raise RuntimeError(
                        "Exception is thrown while running forward of torch_module, please check the legality of module.\n{}".format(
                            str(e)
                        )
                    )

            with register_paddle_hooker(self.layer, self.layer_map):
                try:
                    paddle_output = self.layer(**paddle_input)
                    if self.options["use_loss"]:
                        loss = self.paddle_loss(paddle_output)
                        self.paddle_rep.set_loss(loss)
                    else:
                        loss = tensors_mean(paddle_output, "paddle")
                    if self.options["diff_phase"] == "both" or self.options["diff_phase"] == "backward":
                        loss.backward()
                except Exception as e:
                    raise RuntimeError(
                        "Exception is thrown while running forward of paddle_layer, please check the legality of layer.\n{}".format(
                            str(e)
                        )
                    )
        if not self.options["single_step"]:
            log("Max elementwise output diff is {}".format(max_diff(paddle_output, torch_output)))
