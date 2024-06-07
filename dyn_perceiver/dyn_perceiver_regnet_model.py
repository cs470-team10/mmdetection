import math

from dataclasses import dataclass
from typing import Any, Optional, Tuple

import torch
from einops import rearrange, repeat
from torch import Tensor
import torch.nn as nn
# from fairscale.nn import checkpoint_wrapper
# from fvcore.nn import FlopCountAnalysis, parameter_count_table
from timm.models.registry import register_model
from dyn_perceiver.perceiver_core import (
    CrossAttentionLayer,
    SelfAttentionBlock,
)
from dyn_perceiver.cnn_core import *
import numpy as np

class DynPerceiver(nn.Module):
    def __init__(self,
                input_size: int=224,
                num_classes:int=1000,
                cnn_arch: str="regnet_y_400mf",
                num_SA_heads: list=[1,2,4,8],
                num_latents: int=32,
                num_latent_channels: int=None,
                dropout: float = 0.0,
                SA_widening_factor: int=1,
                activation_checkpointing: bool = False,
                spatial_reduction: bool=False,
                depth_factor: list=[1,1,1,1],
                output_dir: str='./',
                with_x2z=True,
                with_z2x=True,
                with_dwc=True,
                with_last_CA=True,
                with_isc=True,
                zero_padding=False):
        super().__init__()
        if num_SA_heads is None:
            num_SA_heads = [1,2,4,8]
            
        cnn = eval(f'{cnn_arch}')(num_classes=num_classes)  # interpret the cnn_arch string as a class name and instantiate it
        self.cnn_stem = cnn.stem
        self.cnn_body = cnn.trunk_output
        # num_blocks_per_stage = [len(self.cnn_body.block1)*depth_factor[0], len(self.cnn_body.block2)*depth_factor[1], 
        #                         len(self.cnn_body.block3)*depth_factor[2], len(self.cnn_body.block4)*depth_factor[3]]
        num_blocks_per_stage = [3*depth_factor[0], 3*depth_factor[1], 9*depth_factor[2], 3*depth_factor[3]]  # the depth of each stage in the mode
        self.avgpool = cnn.avgpool
        self.spatial_reduction = spatial_reduction  # use SRA rather than MHA
        if spatial_reduction:
            self.ca_pooling = nn.AdaptiveAvgPool2d((7,7))
        self.zero_padding = zero_padding

        """
        functions for initializing cross-attention and self-attention layers respectively.
        """
        def cross_attn(num_cross_attention_heads, q_input_channels, kv_input_channels, num_cross_attention_qk_channels, num_cross_attention_v_channels, cross_attention_widening_factor,
                       rpb=False,
                       feat_w=112,
                       feat_h=112):
            layer = CrossAttentionLayer(
                num_heads=num_cross_attention_heads,
                num_q_input_channels=q_input_channels,
                num_kv_input_channels=kv_input_channels,
                num_qk_channels=num_cross_attention_qk_channels,
                num_v_channels=num_cross_attention_v_channels,
                widening_factor=cross_attention_widening_factor,
                dropout=dropout,

                rpb=rpb,
                feat_w=feat_w,
                feat_h=feat_h,
            )
            return layer

        def self_attn(num_self_attention_layers_per_block, num_self_attention_heads, num_channels, num_self_attention_qk_channels, num_self_attention_v_channels, self_attention_widening_factor):
            return SelfAttentionBlock(
                num_layers=num_self_attention_layers_per_block,
                num_heads=num_self_attention_heads,
                num_channels=num_channels,
                num_qk_channels=num_self_attention_qk_channels,
                num_v_channels=num_self_attention_v_channels,
                widening_factor=self_attention_widening_factor,
                dropout=dropout,
                activation_checkpointing=activation_checkpointing,
            )
        

        # stage1
        """
        the number of input channels for each stage from the CNN model
        이 때, z는 latent code의 channel을 의미 (각 token의 길이)
        """
        x_channels_stage1in = cnn.trunk_output.block1.c_in
        x_channels_stage2in = cnn.trunk_output.block2.c_in
        x_channels_stage3in = cnn.trunk_output.block3.c_in
        x_channels_stage4in = cnn.trunk_output.block4.c_in
        x_channels_stage4out = cnn.trunk_output.block4.c_out
        z_channels = [x_channels_stage1in, x_channels_stage2in, x_channels_stage3in, x_channels_stage4in]
        # print(z_channels)
        # assert(0==1)
        """
        learnable latent parameter for the attention mechanism
        Parameter는 num_latents * num_latent_channels 크기의 matrix로 생각.
        """
        if num_latent_channels is None:
            num_latent_channels = x_channels_stage1in
        self.latent = nn.Parameter(torch.empty(num_latents, num_latent_channels))
        
        """
        x2z and z2x for cross-attention operations and with_dwc for depth-wise convolutions.
        """
        self.with_x2z = with_x2z
        self.with_z2x = with_z2x
        self.with_dwc = with_dwc

        """
        4 stages에 맞게 layer를 Setting 해주는 과정    
        """
        
        # DWC를 통해 local feature extraction 을 enhance하고 cross-attention 전에 7x7 matrix kernel로 Pooling. 
        # 이유 : the token numbers in early features can be large, which is inefficient if we directly conduct cross attention
        if with_dwc:
            self.dwc1_x2z = nn.Conv2d(in_channels=x_channels_stage1in, out_channels=x_channels_stage1in, kernel_size=7, 
                                  groups=x_channels_stage1in, stride=1, padding=3)
        feat_hw = 7 if spatial_reduction else input_size//2
        
        # essential
        self.cross_att1_x2z = cross_attn(num_cross_attention_heads=1,
                                        q_input_channels=x_channels_stage1in,
                                        kv_input_channels=x_channels_stage1in,                     
                                        num_cross_attention_qk_channels=None,       
                                        num_cross_attention_v_channels=None,        
                                        cross_attention_widening_factor=1,

                                        rpb=True,
                                        feat_w=feat_hw,
                                        feat_h=feat_hw,
        )
        self.self_att1 = self_attn(num_self_attention_layers_per_block=num_blocks_per_stage[0],                       
                                   num_self_attention_heads=num_SA_heads[0],                        
                                   num_channels=x_channels_stage1in,
                                   num_self_attention_qk_channels=None,                         
                                   num_self_attention_v_channels=None,                          
                                   self_attention_widening_factor=SA_widening_factor
        )
        
        # stage2
        if with_x2z:
            if with_dwc:
                self.dwc2_x2z = nn.Conv2d(in_channels=x_channels_stage2in, out_channels=x_channels_stage2in, kernel_size=7, groups=x_channels_stage2in, stride=1, padding=3)
            feat_hw = 7 if spatial_reduction else input_size//4
            self.cross_att2_x2z = cross_attn(num_cross_attention_heads=1,
                                        q_input_channels=x_channels_stage2in,
                                        kv_input_channels=x_channels_stage2in,                     
                                        num_cross_attention_qk_channels=None,       
                                        num_cross_attention_v_channels=None,                                      
                                        cross_attention_widening_factor=1,

                                        rpb=True,
                                        feat_w=feat_hw,
                                        feat_h=feat_hw,
            )

        if with_z2x:
            self.cross_att2_z2x = cross_attn(num_cross_attention_heads=1,
                                        q_input_channels=x_channels_stage2in,
                                        kv_input_channels=x_channels_stage2in,                     
                                        num_cross_attention_qk_channels=x_channels_stage2in//8,       
                                        num_cross_attention_v_channels=x_channels_stage2in//8,
                                        cross_attention_widening_factor=1
            )
        self.self_att2 = self_attn(num_self_attention_layers_per_block=num_blocks_per_stage[1], 
                                   num_self_attention_heads=num_SA_heads[1],                                  
                                   num_channels=x_channels_stage2in,
                                   num_self_attention_qk_channels=None,                         
                                   num_self_attention_v_channels=None,                          
                                   self_attention_widening_factor=SA_widening_factor
        )

        # stage3
        if with_x2z:
            if with_dwc:
                self.dwc3_x2z = nn.Conv2d(in_channels=x_channels_stage3in, out_channels=x_channels_stage3in, kernel_size=7, groups=x_channels_stage3in, stride=1, padding=3)
            feat_hw = 7 if spatial_reduction else input_size//8
            self.cross_att3_x2z = cross_attn(num_cross_attention_heads=1,
                                        q_input_channels=x_channels_stage3in,
                                        kv_input_channels=x_channels_stage3in,                     
                                        num_cross_attention_qk_channels=None,       
                                        num_cross_attention_v_channels=None,                                      
                                        cross_attention_widening_factor=1,

                                        rpb=True,
                                        feat_w=feat_hw,
                                        feat_h=feat_hw
            )

        if with_z2x:
            self.cross_att3_z2x = cross_attn(num_cross_attention_heads=1,
                                        q_input_channels=x_channels_stage3in,
                                        kv_input_channels=x_channels_stage3in,                     
                                        num_cross_attention_qk_channels=x_channels_stage3in//8,       
                                        num_cross_attention_v_channels=x_channels_stage3in//8,
                                        cross_attention_widening_factor=1
            )
        self.self_att3 = self_attn(num_self_attention_layers_per_block=num_blocks_per_stage[2],                       
                                   num_self_attention_heads=num_SA_heads[2],                                  
                                   num_channels=x_channels_stage3in,
                                   num_self_attention_qk_channels=None,                         
                                   num_self_attention_v_channels=None,                          
                                   self_attention_widening_factor=SA_widening_factor
        )

        # stage4
        if with_x2z:
            if with_dwc:
                self.dwc4_x2z = nn.Conv2d(in_channels=x_channels_stage4in, out_channels=x_channels_stage4in, kernel_size=7, groups=x_channels_stage4in, stride=1, padding=3)
            feat_hw = 7 if spatial_reduction else input_size//16
            self.cross_att4_x2z = cross_attn(num_cross_attention_heads=1,
                                        q_input_channels=x_channels_stage4in,
                                        kv_input_channels=x_channels_stage4in,                     
                                        num_cross_attention_qk_channels=None,       
                                        num_cross_attention_v_channels=None,                      
                                        cross_attention_widening_factor=1,

                                        rpb=True,
                                        feat_w=feat_hw,
                                        feat_h=feat_hw
            )

        if with_z2x:
            self.cross_att4_z2x = cross_attn(num_cross_attention_heads=1,
                                        q_input_channels=x_channels_stage4in,
                                        kv_input_channels=x_channels_stage4in,                     
                                        num_cross_attention_qk_channels=x_channels_stage4in//8,       
                                        num_cross_attention_v_channels=x_channels_stage4in//8,                      
                                        cross_attention_widening_factor=1
            )
        # print(num_blocks_per_stage[3])
        self.self_att4 = self_attn(num_self_attention_layers_per_block=num_blocks_per_stage[3],                       
                                   num_self_attention_heads=num_SA_heads[3],                                  
                                   num_channels=x_channels_stage4in,
                                   num_self_attention_qk_channels=None,                         
                                   num_self_attention_v_channels=None,                          
                                   self_attention_widening_factor=SA_widening_factor
        )

        # last cross attention 
        # print(x_channels_stage4out//8)
        
        self.last_cross_att_z2x = cross_attn(num_cross_attention_heads=1,
                                        q_input_channels=x_channels_stage4out,
                                        kv_input_channels=x_channels_stage4in,                     
                                        num_cross_attention_qk_channels=x_channels_stage4out//8,       
                                        num_cross_attention_v_channels=x_channels_stage4out//8,                                      
                                        cross_attention_widening_factor=1
        ) if with_last_CA else None

        """
        classifier들을 정의하는 구간

        총 4개의 classifier가 존재한다.
        1) self.classifier_cnn : 기존 regnet에 연결된 classifier
        2) self.early_classifier3 : stage 3에 연결된 classifier
        3) self.classifier_att : stage 4에 연결된 classifier
        4) self.classifier_merge : 두 branch에서 나온 최종 Output을 concatenate한 이 후 사용하는, 최종 classifier

        isc = intermediate stage classifier???
        isc는 논문에 제시된 FKT(Forward Knowledge Tranfer)를 담당하는 module.
        self.with_isc가 False면 이를 무시함.
        """
        self.classifier_cnn = cnn.fc
        # print(x_channels_stage1in, x_channels_stage2in, x_channels_stage3in, x_channels_stage4in)
        # self.early_classifier1 = nn.Linear(x_channels_stage1in, num_classes)
        # self.early_classifier2 = nn.Linear(x_channels_stage2in, num_classes)
        
        self.early_classifier3 = nn.Linear(x_channels_stage3in, num_classes)
        self.with_isc = with_isc
        
        if not with_isc:    
            self.classifier_att = nn.Linear(x_channels_stage4in, num_classes)
            cnn_channels = cnn.fc.weight.shape[1]
            self.classifier_merge = nn.Sequential(nn.BatchNorm1d(cnn_channels+x_channels_stage4in),
                                            nn.Linear(cnn_channels+x_channels_stage4in, num_classes)
            )
        else:
            self.isc3 = nn.Sequential(nn.Linear(num_classes, x_channels_stage4in),
                                    nn.BatchNorm1d(x_channels_stage4in),
                                    nn.ReLU(inplace=True)
                                    )

            self.classifier_att = nn.Linear(2*x_channels_stage4in, num_classes)
            self.isc4 = nn.Sequential(nn.Linear(num_classes, x_channels_stage4in),
                                        nn.BatchNorm1d(x_channels_stage4in),
                                        nn.ReLU(inplace=True)
                                        )
            cnn_channels = cnn.fc.weight.shape[1]
            self.classifier_merge = nn.Sequential(nn.BatchNorm1d(cnn_channels+2*x_channels_stage4in),
                                        nn.Linear(cnn_channels+2*x_channels_stage4in, num_classes)
            )
        

        """
        Token Mixer와 내부의 expander를 setting하는 part
        (각 stage에서 token의 갯수와 channel을 가지고, initialize)
        """
        expander = []
        token_mixer = []

        num_latents_list = [num_latents, num_latents//2, num_latents//4, num_latents//8]
        for i in range(3):
            c_in = z_channels[i]
            c_out = z_channels[i+1]
            expander.append(nn.Sequential(
                nn.LayerNorm(c_in),
                nn.Linear(c_in, c_out)
            ))

            # linear_layer = nn.Linear(c_in, 2, bias=True)
            # linear_layer.bias.data[0] = 0.0
            # linear_layer.bias.data[1] = 0.0
            # token_mixer.append(nn.Sequential(
            #     nn.LayerNorm(c_in),
            #     linear_layer
            # ))
            n_z_in = num_latents_list[i]
            n_z_out = num_latents_list[i+1]
            token_mixer.append(nn.Sequential(
                nn.LayerNorm(n_z_in),
                nn.Linear(n_z_in, n_z_out)
            ))

        self.token_expander = nn.ModuleList(expander)
        self.token_mixer = nn.ModuleList(token_mixer)
        self.output_dir = output_dir
        self._init_parameters()
        """
        FLOPs를 미리 계산하기 위해서 garbage value를 넣고 model을 한번 수행함.
        """
        x = torch.rand(2,3,1333,800)
        self.forward_calc_flops(x)

        self.softmax = nn.Softmax(dim=1).cuda()
        self.last_exited_stage = 4
        self.output_fmap_sizes = [[1, 64, 200, 304], [1, 144, 100, 152], [1, 320, 50, 76], [1, 784, 25, 38]]

    def get_last_exited_stage(self):
        return self.last_exited_stage

    def _init_parameters(self):
        """
        latent code를 initialize하는 함수
        """
        with torch.no_grad():
            self.latent.normal_(0.0, 0.02).clamp_(-2.0, 2.0)

    def forward(self, x, pad_mask=None, threshold=None):
        """_summary_
        forward 연산을 수행.

        Args:
            x : input image
            pad_mask : Defaults to None.

        Returns:
            각 classifier의 prediction. y_early3, y_att, y_cnn, y_merge 
        """

        outs = []

        #TODO
        b, c_in, _, _ = x.shape
        x_latent = repeat(self.latent, "... -> b ...", b=b)

        x = self.cnn_stem(x)
        # before stage1
        # conv to transformer
        # print(x.shape)
        if self.with_dwc:
            x_kv = self.dwc1_x2z(x) + x
            x_kv = self.ca_pooling(x_kv)
        else:
            x_kv = self.ca_pooling(x)
        x_kv = rearrange(x_kv, "b c ... -> b (...) c")
        # print(x_latent.shape, x_kv.shape)
        x_latent = self.cross_att1_x2z(x_latent, x_kv, pad_mask)

        # stage1, conv and self attention
        x_latent = self.self_att1(x_latent)

        # y_early1 = torch.mean(x_latent, dim=1).squeeze(1)
        # y_early1 = self.early_classifier1(y_early1)

        x = self.cnn_body.block1(x)

        # between stage1 and stage2
        _, n_tokens, c_in = x_latent.shape
        x_latent = x_latent.permute(0,2,1)
        x_latent = self.token_mixer[0](x_latent)
        x_latent = x_latent.permute(0,2,1)
        x_latent = self.token_expander[0](x_latent)
        
        # transformer to conv
        if self.with_z2x:
            _,_,h,w = x.shape
            x = rearrange(x, "b c ... -> b (...) c")
            x = self.cross_att2_z2x(x, x_latent, pad_mask)
            x = rearrange(x, "b (h w) c -> b c h w", h=h, w=w)

        # conv to transformer
        if self.with_x2z:
            if self.with_dwc:
                x_kv = self.dwc2_x2z(x) + x
                x_kv = self.ca_pooling(x_kv)
            else:
                x_kv = self.ca_pooling(x)
            x_kv = rearrange(x_kv, "b c ... -> b (...) c")
            x_latent = self.cross_att2_x2z(x_latent, x_kv, pad_mask)
        
        # stage2
        x_latent = self.self_att2(x_latent)
        # y_early2 = torch.mean(x_latent, dim=1).squeeze(1)
        # y_early2 = self.early_classifier2(y_early2)
        outs.append(x)
        x = self.cnn_body.block2(x)

        # between stage2 and stage3
        _, n_tokens, c_in = x_latent.shape
        x_latent = x_latent.permute(0,2,1)
        x_latent = self.token_mixer[1](x_latent)
        x_latent = x_latent.permute(0,2,1)
        x_latent = self.token_expander[1](x_latent)
        
        # transformer to conv
        if self.with_z2x:
            _,_,h,w = x.shape
            x = rearrange(x, "b c ... -> b (...) c")
            x = self.cross_att3_z2x(x, x_latent, pad_mask)
            x = rearrange(x, "b (h w) c -> b c h w", h=h, w=w)

        # conv to transformer
        if self.with_x2z:
            if self.with_dwc:
                x_kv = self.dwc3_x2z(x) + x
                x_kv = self.ca_pooling(x_kv)
            else:
                x_kv = self.ca_pooling(x)
            x_kv = rearrange(x_kv, "b c ... -> b (...) c")
            x_latent = self.cross_att3_x2z(x_latent, x_kv, pad_mask)

        # stage3
        x_latent = self.self_att3(x_latent)
        y_early3 = torch.mean(x_latent, dim=1).squeeze(1)
        y_early3 = self.early_classifier3(y_early3)
        outs.append(x)

        logits = [[] for _ in range(1)]
        if threshold is not None:
            _t = self.softmax(y_early3)
            logits[0].append(_t)
            logits[0] = torch.cat(logits[0], dim=0)

            size = (1, logits[0].size(0), logits[0].size(1))
            ts_logits = torch.Tensor().resize_(size).zero_()
            ts_logits[0].copy_(logits[0])

            _, n_sample, _ =  ts_logits.size()
            max_preds, _ = ts_logits.max(dim=2, keepdim=False)

            for i in range(n_sample):
                if max_preds[0][i].item() >= threshold[0]:
                    self.last_exited_stage = 1
                    if self.zero_padding:
                        for k in range(2, 4):
                            outs.append(torch.zeros(*self.output_fmap_sizes[k]).cuda())
            
                    return y_early3, torch.zeros_like(y_early3), torch.zeros_like(y_early3), torch.zeros_like(y_early3), outs 

        x = self.cnn_body.block3(x)

        # between stage3 and stage4
        _, n_tokens, c_in = x_latent.shape
        x_latent = x_latent.permute(0,2,1)
        x_latent = self.token_mixer[2](x_latent)
        x_latent = x_latent.permute(0,2,1)
        x_latent = self.token_expander[2](x_latent)

        # transformer to conv
        if self.with_z2x:
            _,_,h,w = x.shape
            x = rearrange(x, "b c ... -> b (...) c")
            # print(x_latent.shape, x.shape)
            x = self.cross_att4_z2x(x, x_latent, pad_mask)
            x = rearrange(x, "b (h w) c -> b c h w", h=h, w=w)


        # conv to transformer
        if self.with_x2z:
            if self.with_dwc:
                x_kv = self.dwc4_x2z(x) + x
                x_kv = self.ca_pooling(x_kv)
            else:
                x_kv = self.ca_pooling(x)
            x_kv = rearrange(x_kv, "b c ... -> b (...) c")
            x_latent = self.cross_att4_x2z(x_latent, x_kv, pad_mask)

        # stage4
        x_latent = self.self_att4(x_latent)

        x_latent_mean = torch.mean(x_latent, dim=1).squeeze(1)
        if self.with_isc:
            y3_ = self.isc3(y_early3)
            y_att = torch.cat((x_latent_mean, y3_), dim=1)
            y_att = self.classifier_att(y_att)
        else:
            y_att = self.classifier_att(x_latent_mean)
        outs.append(x)

        logits = [[] for _ in range(1)]
        if threshold is not None:
            _t = self.softmax(y_att)
            logits[0].append(_t)
            logits[0] = torch.cat(logits[0], dim=0)

            size = (1, logits[0].size(0), logits[0].size(1))
            ts_logits = torch.Tensor().resize_(size).zero_()
            ts_logits[0].copy_(logits[0])

            _, n_sample, _ =  ts_logits.size()
            max_preds, _ = ts_logits.max(dim=2, keepdim=False)

            for i in range(n_sample):
                if max_preds[0][i].item() >= threshold[1]:
                    self.last_exited_stage = 2 
                    if self.zero_padding:
                        for k in range(3, 4):
                            outs.append(torch.zeros(*self.output_fmap_sizes[k]).cuda())
            
                    return y_early3, y_att, torch.zeros_like(y_att), torch.zeros_like(y_att), outs 

        x = self.cnn_body.block4(x)

        x_mean = self.avgpool(x)
        x_mean = x_mean.flatten(start_dim=1)
        y_cnn = self.classifier_cnn(x_mean)
        
        logits = [[] for _ in range(1)]
        if threshold is not None:
            _t = self.softmax(y_cnn)
            logits[0].append(_t)
            logits[0] = torch.cat(logits[0], dim=0)

            size = (1, logits[0].size(0), logits[0].size(1))
            ts_logits = torch.Tensor().resize_(size).zero_()
            ts_logits[0].copy_(logits[0])

            _, n_sample, _ =  ts_logits.size()
            max_preds, _ = ts_logits.max(dim=2, keepdim=False)

            for i in range(n_sample):
                if max_preds[0][i].item() >= threshold[2]:
                    self.last_exited_stage = 3
                    outs.append(x)
            
                    return y_early3, y_att, y_cnn, torch.zeros_like(y_cnn), outs

        # cross attention from z to x
        if self.last_cross_att_z2x is not None:
            _,_,h,w = x.shape
            x = rearrange(x, "b c ... -> b (...) c")
            x = self.last_cross_att_z2x(x, x_latent, pad_mask)
            x = rearrange(x, "b (h w) c -> b c h w", h=h, w=w)
            x_mean = self.avgpool(x)
            x_mean = x_mean.flatten(start_dim=1)
        outs.append(x)

        if self.with_isc:
            y4_ = self.isc4(y_att)
            x_merge = torch.cat((x_mean, x_latent_mean, y4_), dim=1)
            y_merge = self.classifier_merge(x_merge)
        else:
            x_merge = torch.cat((x_mean, x_latent_mean), dim=1)
            y_merge = self.classifier_merge(x_merge)

        """
        logits = [[] for _ in range(4)]
        if threshold is not None:
            output = [y_early3, y_att, y_cnn, y_merge]
            for b in range(4):
                _t = self.softmax(output[b])
                logits[b].append(_t)

            for b in range(4):
                logits[b] = torch.cat(logits[b], dim=0)

            size = (4, logits[0].size(0), logits[0].size(1))
            ts_logits = torch.Tensor().resize_(size).zero_()
            for b in range(4):
                ts_logits[b].copy_(logits[b])
            
            n_stage, n_sample, _ =  ts_logits.size()
            max_preds, _ = ts_logits.max(dim=2, keepdim=False)

            for i in range(n_sample):
                for k in range(n_stage):
                    if max_preds[k][i].item() >= threshold[k]:
                        self.last_exited_stage = k + 1 # 어느 스테이지에서 exit했는지 정보 필요. 1~4 range
                        for j in range(k+1, n_stage):
                            outs[j][i].zero_()
        """
        if threshold is not None:
            self.last_exited_stage = 4

        return y_early3, y_att, y_cnn, y_merge, outs


    def forward_calc_flops(self, x, pad_mask=None):
        """_summary_
        Model을 처음 Instansiate할 때, 각 단계의 FLOPs를 구하기 위해 실행하는 함수.
        계산된 FLOPs는 {self.output_dir}/flops.txt 에 저장된다.
        inference에서 총 소요된 FLOPs를 계산하기 위해서 사용된다.

        Args:
            x : garbage input
            pad_mask : Defaults to None.

        Returns:
            각 classifier의 grabage prediction. y_early3, y_att, y_cnn, y_merge
        """
        #TODO
        b, c_in, _, _ = x.shape
        x_latent = repeat(self.latent, "... -> b ...", b=b)
        
        cnn_flops = 0
        att_flops = 0

        x = self.cnn_stem(x)
        stem_flops = c_in * x.shape[1] * x.shape[2] * x.shape[3] * 9
        cnn_flops += stem_flops
        # before stage1
        # conv to transformer
        if self.with_dwc:
            x_kv = self.dwc1_x2z(x) + x
            att_flops += x_kv.shape[1] * x_kv.shape[2] * x_kv.shape[3] * 49
            x_kv = self.ca_pooling(x_kv)
        else:
            x_kv = self.ca_pooling(x)
        att_flops += x.shape[1] * x.shape[2] * x.shape[3] # pooling flops
        
        x_kv = rearrange(x_kv, "b c ... -> b (...) c")
        x_latent, CA1x2z_flops = self.cross_att1_x2z.forward_calc_flops(x_latent, x_kv, pad_mask)
        att_flops += CA1x2z_flops

        # stage1, conv and self attention
        x_latent, SA1_flops = self.self_att1.forward_calc_flops(x_latent)
        att_flops += SA1_flops

        # c_in = x_latent.shape[-1]
        # y_early1 = torch.mean(x_latent, dim=1).squeeze(1)
        # y_early1 = self.early_classifier1(y_early1)
        # flops_early1 = cnn_flops + att_flops + c_in*y_early1.shape[-1]

        x, stage1_flops = self.cnn_body.block1.forward_calc_flops(x)
        cnn_flops += stage1_flops
        # assert(0==1)

        # between stage1 and stage2
        _, n_tokens, c_in = x_latent.shape
        x_latent = x_latent.permute(0,2,1)
        x_latent = self.token_mixer[0](x_latent)
        x_latent = x_latent.permute(0,2,1)
        att_flops += c_in * n_tokens * x_latent.shape[1]

        x_latent = self.token_expander[0](x_latent)
        att_flops += n_tokens * c_in * x_latent.shape[-1]
        # transformer to conv
        
        CA2z2x_flops = 0
        if self.with_z2x:
            _,_,h,w = x.shape
            x = rearrange(x, "b c ... -> b (...) c")
            x, CA2z2x_flops = self.cross_att2_z2x.forward_calc_flops(x, x_latent, pad_mask)
            x = rearrange(x, "b (h w) c -> b c h w", h=h, w=w)
            att_flops += CA2z2x_flops
        
        
        # conv to transformer
        CA2_x2z_flops = 0
        if self.with_x2z:
            if self.with_dwc:
                x_kv = self.dwc2_x2z(x) + x
                att_flops += x_kv.shape[1] * x_kv.shape[2] * x_kv.shape[3] * 49
                x_kv = self.ca_pooling(x_kv)
            else:
                x_kv = self.ca_pooling(x)
            
            att_flops += x.shape[1] * x.shape[2] * x.shape[3]
            x_kv = rearrange(x_kv, "b c ... -> b (...) c")
            x_latent, CA2_x2z_flops = self.cross_att2_x2z.forward_calc_flops(x_latent, x_kv, pad_mask)
            att_flops += CA2_x2z_flops
        
        # stage2
        x_latent, SA2_flops = self.self_att2.forward_calc_flops(x_latent)
        att_flops += SA2_flops
        c_in = x_latent.shape[-1]
        # y_early2 = torch.mean(x_latent, dim=1).squeeze(1)
        # y_early2 = self.early_classifier2(y_early2)
        # flops_early2 = cnn_flops + att_flops + c_in*y_early2.shape[-1]

        x, stage2_flops = self.cnn_body.block2.forward_calc_flops(x)
        cnn_flops += stage2_flops

        # between stage2 and stage3
        _, n_tokens, c_in = x_latent.shape
        x_latent = x_latent.permute(0,2,1)
        x_latent = self.token_mixer[1](x_latent)
        x_latent = x_latent.permute(0,2,1)
        att_flops += c_in * n_tokens * x_latent.shape[1]
        x_latent = self.token_expander[1](x_latent)
        att_flops += n_tokens * c_in * x_latent.shape[-1]
        
        # transformer to conv
        CA3z2x_flops = 0
        if self.with_z2x:
            _,_,h,w = x.shape
            x = rearrange(x, "b c ... -> b (...) c")
            x, CA3z2x_flops = self.cross_att3_z2x.forward_calc_flops(x, x_latent, pad_mask)
            x = rearrange(x, "b (h w) c -> b c h w", h=h, w=w)
            att_flops += CA3z2x_flops
        
        
        # conv to transformer
        CA3x2z_flops = 0
        if self.with_x2z:
            if self.with_dwc:
                x_kv = self.dwc3_x2z(x) + x
                att_flops += x_kv.shape[1] * x_kv.shape[2] * x_kv.shape[3] * 49
                x_kv = self.ca_pooling(x_kv)
            else:
                x_kv = self.ca_pooling(x)
            
            att_flops += x.shape[1] * x.shape[2] * x.shape[3]
            x_kv = rearrange(x_kv, "b c ... -> b (...) c")
            # print(x_latent.shape, x_kv.shape)
            x_latent, CA3x2z_flops = self.cross_att3_x2z.forward_calc_flops(x_latent, x_kv, pad_mask)
            att_flops += CA3x2z_flops

        # stage3
        x_latent, SA3_flops = self.self_att3.forward_calc_flops(x_latent)
        att_flops += SA3_flops
        c_in = x_latent.shape[-1]
        y_early3 = torch.mean(x_latent, dim=1).squeeze(1)
        y_early3 = self.early_classifier3(y_early3)
        flops_early3 = cnn_flops + att_flops + c_in*y_early3.shape[-1]

        x, stage3_flops = self.cnn_body.block3.forward_calc_flops(x)
        cnn_flops += stage3_flops

        # between stage3 and stage4
        _, n_tokens, c_in = x_latent.shape
        x_latent = x_latent.permute(0,2,1)
        x_latent = self.token_mixer[2](x_latent)
        x_latent = x_latent.permute(0,2,1)
        att_flops += c_in * n_tokens * x_latent.shape[1]
        x_latent = self.token_expander[2](x_latent)
        att_flops += n_tokens * c_in * x_latent.shape[-1]
        
        
        # transformer to conv
        CA4z2x_flops = 0
        if self.with_z2x:
            _,_,h,w = x.shape
            x = rearrange(x, "b c ... -> b (...) c")
            x, CA4z2x_flops = self.cross_att4_z2x.forward_calc_flops(x, x_latent, pad_mask)
            x = rearrange(x, "b (h w) c -> b c h w", h=h, w=w)
            att_flops += CA4z2x_flops

        # conv to transformer 
        CA4x2z_flops = 0       
        if self.with_x2z:
            if self.with_dwc:
                x_kv = self.dwc4_x2z(x) + x
                att_flops += x_kv.shape[1] * x_kv.shape[2] * x_kv.shape[3] * 49
                x_kv = self.ca_pooling(x_kv)
            else:
                x_kv = self.ca_pooling(x)
            att_flops += x.shape[1] * x.shape[2] * x.shape[3]
            x_kv = rearrange(x_kv, "b c ... -> b (...) c")
            # print(x_latent.shape, x_kv.shape)
            x_latent, CA4x2z_flops = self.cross_att4_x2z.forward_calc_flops(x_latent, x_kv, pad_mask)
            att_flops += CA4x2z_flops

        # stage4
        x_latent, SA4_flops = self.self_att4.forward_calc_flops(x_latent)
        att_flops += SA4_flops

        att_flops += x_latent.shape[1] * x_latent.shape[2]
        x_latent_mean = torch.mean(x_latent, dim=1).squeeze(1)
        if self.with_isc:
            c_in_ = y_early3.shape[-1]
            y3_ = self.isc3(y_early3)
            c_out_ = y3_.shape[-1]
            y_att = torch.cat((x_latent_mean, y3_), dim=1)
            c_in_att = y_att.shape[1]
            y_att = self.classifier_att(y_att)
            flops_early4 = cnn_flops + att_flops + c_in_att*y_att.shape[1] + c_in_ * c_out_
        else:
            c_in_att = x_latent_mean.shape[1]
            y_att = self.classifier_att(x_latent_mean)
            flops_early4 = cnn_flops + att_flops + c_in_att*y_att.shape[1]


        x, stage4_flops = self.cnn_body.block4.forward_calc_flops(x)
        cnn_flops += stage4_flops

        cnn_flops += x.shape[1]*x.shape[2]*x.shape[3]
        x_mean = self.avgpool(x)
        x_mean = x_mean.flatten(start_dim=1)
        c_in_cnn = x_mean.shape[1]
        y_cnn = self.classifier_cnn(x_mean)
        cnn_flops += c_in_cnn * y_cnn.shape[1]
        flops_early5 = cnn_flops + att_flops
        
        lastCA_flops = 0
        if self.last_cross_att_z2x is not None:
            # cross attention from z to x
            _,_,h,w = x.shape
            x = rearrange(x, "b c ... -> b (...) c")
            
            # print(x_latent.shape, x.shape)
            x, lastCA_flops = self.last_cross_att_z2x.forward_calc_flops(x, x_latent, pad_mask)
            x = rearrange(x, "b (h w) c -> b c h w", h=h, w=w)
            # x = x + x_q
            att_flops += lastCA_flops

            cnn_flops += x.shape[1]*x.shape[2]*x.shape[3]
            x_mean = self.avgpool(x)
            x_mean = x_mean.flatten(start_dim=1)
        
        if self.with_isc:
            c_in_ = y_att.shape[-1]
            y4_ = self.isc4(y_att)
            c_out_ = y4_.shape[-1]
            x_merge = torch.cat((x_mean, x_latent_mean, y4_), dim=1)
        else:
            x_merge = torch.cat((x_mean, x_latent_mean), dim=1)
        c_in = x_merge.shape[-1]
        y_merge = self.classifier_merge(x_merge)
        flops = att_flops + cnn_flops + c_in*y_merge.shape[1]

        # print(f'total flops: {flops/1e9}\n\
        #     att_flops: {att_flops/1e9}\n\
        #     cnn_flops: {cnn_flops/1e9}\n\n\
        #     CA1x2z_flops: {CA1x2z_flops/1e8}\n\
        #     SA1_flops: {SA1_flops/1e8}\n\
        #     stage1_flops: {stage1_flops/1e8}\n\
        #     CA2z2x_flops: {CA2z2x_flops/1e8}\n\
        #     CA2_x2z_flops: {CA2_x2z_flops/1e8}\n\
        #     SA2_flops: {SA2_flops/1e8}\n\
        #     stage2_flops: {stage2_flops/1e8}\n\
        #     CA3z2x_flops: {CA3z2x_flops/1e8}\n\
        #     CA3x2z_flops: {CA3x2z_flops/1e8}\n\
        #     SA3_flops: {SA3_flops/1e8}\n\
        #     EE3_flops: {flops_early3/1e9}\n\n\
        #     stage3_flops: {stage3_flops/1e8}\n\
        #     CA4z2x_flops: {CA4z2x_flops/1e8}\n\
        #     CA4x2z_flops: {CA4x2z_flops/1e8}\n\
        #     SA4_flops: {SA4_flops/1e8}\n\
        #     EE4_flops: {flops_early4/1e9}\n\n\
        #     stage4_flops: {stage4_flops/1e8}\n\
        #     lastCA_flops: {lastCA_flops/1e8}')
        
        all_flops = [flops_early3/1e9, flops_early4/1e9, flops_early5/1e9, flops/1e9]
        # print(all_flops)
        np.savetxt(f'{self.output_dir}/flops.txt', all_flops)
        return y_early3, y_att, y_cnn, y_merge


@register_model
def reg400m_perceiver_t32(**kwargs):
    model = DynPerceiver(num_latents=32, cnn_arch='regnet_y_400mf', **kwargs)
    return model


@register_model
def reg400m_perceiver_t64(**kwargs):
    model = DynPerceiver(num_latents=64, cnn_arch='regnet_y_400mf', **kwargs)
    return model


@register_model
def reg400m_perceiver_t128(**kwargs):
    model = DynPerceiver(num_latents=128, cnn_arch='regnet_y_400mf', **kwargs)
    return model


@register_model
def reg400m_perceiver_t256(**kwargs):
    model = DynPerceiver(num_latents=256, cnn_arch='regnet_y_400mf', **kwargs)
    return model


@register_model
def reg400m_perceiver_t512(**kwargs):
    model = DynPerceiver(num_latents=512, cnn_arch='regnet_y_400mf', **kwargs)
    return model


@register_model
def reg800m_perceiver_t32(**kwargs):
    model = DynPerceiver(num_latents=32, cnn_arch='regnet_y_800mf', **kwargs)
    return model


@register_model
def reg800m_perceiver_t64(**kwargs):
    model = DynPerceiver(num_latents=64, cnn_arch='regnet_y_800mf', **kwargs)
    return model


@register_model
def reg800m_perceiver_t128(**kwargs):
    model = DynPerceiver(num_latents=128, cnn_arch='regnet_y_800mf', **kwargs)
    return model


@register_model
def reg800m_perceiver_t256(**kwargs):
    model = DynPerceiver(num_latents=256, cnn_arch='regnet_y_800mf', **kwargs)
    return model


@register_model
def reg800m_perceiver_t512(**kwargs):
    model = DynPerceiver(num_latents=512, cnn_arch='regnet_y_800mf', **kwargs)
    return model


@register_model
def reg1x6g_perceiver_t128(**kwargs):
    model = DynPerceiver(num_latents=128, cnn_arch='regnet_y_1_6gf', **kwargs)
    return model


@register_model
def reg1x6g_perceiver_t256(**kwargs):
    model = DynPerceiver(num_latents=256, cnn_arch='regnet_y_1_6gf', **kwargs)
    return model


@register_model
def reg1x6g_perceiver_t512(**kwargs):
    model = DynPerceiver(num_latents=512, cnn_arch='regnet_y_1_6gf', **kwargs)
    return model


@register_model
def reg3x2g_perceiver_t128(**kwargs):
    model = DynPerceiver(num_latents=128, cnn_arch='regnet_y_3_2gf', **kwargs)
    return model


@register_model
def reg3x2g_perceiver_t256(**kwargs):
    model = DynPerceiver(num_latents=256, cnn_arch='regnet_y_3_2gf', **kwargs)
    return model


@register_model
def reg3x2g_perceiver_t512(**kwargs):
    model = DynPerceiver(num_latents=512, cnn_arch='regnet_y_3_2gf', **kwargs)
    return model


if __name__ == '__main__':

    # # Fourier-encodes pixel positions and flatten along spatial dimensions
    # input_adapter = ImageInputAdapter(
    # image_shape=(224, 224, 3),  # M = 224 * 224
    # num_frequency_bands=64,
    # )

    # # Projects generic Perceiver decoder output to specified number of classes
    # output_adapter = ClassificationOutputAdapter(
    # num_classes=1000,
    # num_output_query_channels=1024,  # F
    # )

    # # Generic Perceiver encoder
    # encoder = PerceiverEncoder(
    # input_adapter=input_adapter,
    # num_latents=512,  # N
    # num_latent_channels=1024,  # D
    # num_cross_attention_qk_channels=input_adapter.num_input_channels,  # C
    # num_cross_attention_heads=1,
    # num_self_attention_heads=4,
    # num_self_attention_layers_per_block=6,
    # num_self_attention_blocks=8,
    # dropout=0.0,
    # )

    # # Generic Perceiver decoder
    # decoder = PerceiverDecoder(
    # output_adapter=output_adapter,
    # num_latent_channels=1024,  # D
    # num_cross_attention_heads=1,
    # dropout=0.0,
    # )

    # # Perceiver IO image classifier
    # model = PerceiverIO(encoder, decoder)
    # model.eval()
    # print(model)
    # x = torch.rand(4,224,224,3)
    # with torch.no_grad():
    #     y = model(x)

    #     print(y.shape)





    # regnet = regnet_y_400mf()
    # print(regnet)
    # print(regnet.trunk_output.block1)

    def count_parameters(model):
        return sum(p.numel() for p in model.parameters() if p.requires_grad)

    model = reg400m_perceiver_t128(depth_factor=[2,2,1,2], SA_widening_factor=4, spatial_reduction=True, with_last_CA=True,
                                      with_x2z=True, with_dwc=True, with_z2x=True)
    model.eval()
    print(count_parameters(model)/1e6)
    x = torch.rand(1,3,224,224)
    with torch.no_grad():
        y = model(x)
        # print(y.shape)
        # print()
        # flops = FlopCountAnalysis(model, x)
        # print("FLOPs: ", flops.total()/1e9)
        # from fvcore.nn import flop_count_str
        # print(flop_count_str(flops))
        # # 分析parameters
        # print(parameter_count_table(model))