from copy import deepcopy

import pytest
import torch
import torch.nn as nn
from torch.nn.parallel import DataParallel

from mmgen.core.hooks import ExponentialMovingAverageHook


class SimpleModule(nn.Module):

    def __init__(self):
        super().__init__()
        self.a = nn.Parameter(torch.tensor([1., 2.]))
        if torch.__version__ >= '1.7.0':
            self.register_buffer('b', torch.tensor([2., 3.]), persistent=True)
            self.register_buffer('c', torch.tensor([0., 1.]), persistent=False)
        else:
            self.register_buffer('b', torch.tensor([2., 3.]))
            self.c = torch.tensor([0., 1.])


class SimpleModel(nn.Module):

    def __init__(self) -> None:
        super().__init__()
        self.module_a = SimpleModule()
        self.module_b = SimpleModule()

        self.module_a_ema = SimpleModule()
        self.module_b_ema = SimpleModule()


class SimpleModelNoEMA(nn.Module):

    def __init__(self) -> None:
        super().__init__()
        self.module_a = SimpleModule()
        self.module_b = SimpleModule()


class SimpleRunner:

    def __init__(self):
        self.model = SimpleModel()
        self.iter = 0


class TestEMA:

    @classmethod
    def setup_class(cls):
        cls.default_config = dict(
            module_keys=('module_a_ema', 'module_b_ema'),
            interval=1,
            interp_cfg=dict(momentum=0.5))
        cls.runner = SimpleRunner()

    @torch.no_grad()
    def test_ema_hook(self):
        cfg_ = deepcopy(self.default_config)
        cfg_['interval'] = -1
        ema = ExponentialMovingAverageHook(**cfg_)
        ema.before_run(self.runner)
        ema.after_train_iter(self.runner)

        module_a = self.runner.model.module_a
        module_a_ema = self.runner.model.module_a_ema

        ema_states = module_a_ema.state_dict()
        assert torch.equal(ema_states['a'], torch.tensor([1., 2.]))

        ema = ExponentialMovingAverageHook(**self.default_config)
        ema.after_train_iter(self.runner)

        ema_states = module_a_ema.state_dict()
        assert torch.equal(ema_states['a'], torch.tensor([1., 2.]))

        module_a.b /= 2.
        module_a.a.data /= 2.
        module_a.c /= 2.

        self.runner.iter += 1
        ema.after_train_iter(self.runner)
        ema_states = module_a_ema.state_dict()
        assert torch.equal(self.runner.model.module_a.a,
                           torch.tensor([0.5, 1.]))
        assert torch.equal(ema_states['a'], torch.tensor([0.75, 1.5]))
        assert torch.equal(ema_states['b'], torch.tensor([1., 1.5]))
        assert 'c' not in ema_states

        # check for the validity of args
        with pytest.raises(AssertionError):
            _ = ExponentialMovingAverageHook(module_keys=['a'])

        with pytest.raises(AssertionError):
            _ = ExponentialMovingAverageHook(module_keys=('a'))

        with pytest.raises(AssertionError):
            _ = ExponentialMovingAverageHook(
                module_keys=('module_a_ema'), interp_mode='xxx')

        # test before run
        ema = ExponentialMovingAverageHook(**self.default_config)
        self.runner.model = SimpleModelNoEMA()
        self.runner.iter = 0
        ema.before_run(self.runner)
        assert hasattr(self.runner.model, 'module_a_ema')

        module_a = self.runner.model.module_a
        module_a_ema = self.runner.model.module_a_ema

        ema.after_train_iter(self.runner)
        ema_states = module_a_ema.state_dict()
        assert torch.equal(ema_states['a'], torch.tensor([1., 2.]))

        module_a.b /= 2.
        module_a.a.data /= 2.
        module_a.c /= 2.

        self.runner.iter += 1
        ema.after_train_iter(self.runner)
        ema_states = module_a_ema.state_dict()
        assert torch.equal(self.runner.model.module_a.a,
                           torch.tensor([0.5, 1.]))
        assert torch.equal(ema_states['a'], torch.tensor([0.75, 1.5]))
        assert torch.equal(ema_states['b'], torch.tensor([1., 1.5]))
        assert 'c' not in ema_states

    @pytest.mark.skipif(not torch.cuda.is_available(), reason='requires cuda')
    def test_ema_hook_cuda(self):
        ema = ExponentialMovingAverageHook(**self.default_config)
        cuda_runner = SimpleRunner()
        cuda_runner.model = cuda_runner.model.cuda()
        ema.after_train_iter(cuda_runner)

        module_a = cuda_runner.model.module_a
        module_a_ema = cuda_runner.model.module_a_ema

        ema_states = module_a_ema.state_dict()
        assert torch.equal(ema_states['a'], torch.tensor([1., 2.]).cuda())

        module_a.b /= 2.
        module_a.a.data /= 2.
        module_a.c /= 2.

        cuda_runner.iter += 1
        ema.after_train_iter(cuda_runner)
        ema_states = module_a_ema.state_dict()
        assert torch.equal(cuda_runner.model.module_a.a,
                           torch.tensor([0.5, 1.]).cuda())
        assert torch.equal(ema_states['a'], torch.tensor([0.75, 1.5]).cuda())
        assert torch.equal(ema_states['b'], torch.tensor([1., 1.5]).cuda())
        assert 'c' not in ema_states

        # test before run
        ema = ExponentialMovingAverageHook(**self.default_config)
        self.runner.model = SimpleModelNoEMA().cuda()
        self.runner.model = DataParallel(self.runner.model)
        self.runner.iter = 0
        ema.before_run(self.runner)
        assert hasattr(self.runner.model.module, 'module_a_ema')

        module_a = self.runner.model.module.module_a
        module_a_ema = self.runner.model.module.module_a_ema

        ema.after_train_iter(self.runner)
        ema_states = module_a_ema.state_dict()
        assert torch.equal(ema_states['a'], torch.tensor([1., 2.]).cuda())

        module_a.b /= 2.
        module_a.a.data /= 2.
        module_a.c /= 2.

        self.runner.iter += 1
        ema.after_train_iter(self.runner)
        ema_states = module_a_ema.state_dict()
        assert torch.equal(self.runner.model.module.module_a.a,
                           torch.tensor([0.5, 1.]).cuda())
        assert torch.equal(ema_states['a'], torch.tensor([0.75, 1.5]).cuda())
        assert torch.equal(ema_states['b'], torch.tensor([1., 1.5]).cuda())
        assert 'c' not in ema_states