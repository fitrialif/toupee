#!/usr/bin/python
"""
Alan Mosca
Department of Computer Science and Information Systems
Birkbeck, University of London

All code released under Apachev2.0 licensing.
"""
__docformat__ = 'restructedtext en'

import numpy
import theano
import theano.tensor as T
import theano.printing
import yaml
from data import sharedX
import common

class UpdateRule(yaml.YAMLObject):

    def __call__(self, param, learning_rate, gparam, mask, updates,
                 current_cost, previous_cost):
        raise NotImplementedError()

    def serialize(self):
        raise NotImplementedError()

class SGD(UpdateRule):

    yaml_tag = u'!SGD'

    def __new__(cls):
        instance = super(SGD,cls).__new__(cls)
        common.toupee_global_instance.add_epoch_hook(lambda x: instance.epoch_hook(x))
        common.toupee_global_instance.add_reset_hook(lambda x: instance.reset(x))
        return instance

    def reset(self,updates):
        if 'momentum' not in self.__dict__:
            self.momentum = 0.
        if 'momentum_decay' not in self.__dict__:
            self.momentum_decay = 1.
        if 'renorm' not in self.__dict__:
            self.renorm = False
        self.curr_momentum = sharedX(self.momentum)

    def epoch_hook(self,updates):
        updates.append((self.curr_momentum,self.curr_momentum * self.momentum_decay))

    def __init__(self):
        pass

    def __call__(self, param, learning_rate, gparam, mask, updates,
                 current_cost, previous_cost):
        self.velocity = sharedX(numpy.zeros(param.shape.eval()),borrow=True)
        if self.momentum:
            velocity = (self.velocity * self.curr_momentum - learning_rate.get() * gparam)
        else:
            velocity = - learning_rate.get() * gparam
        new_w = param + velocity * mask
        if self.renorm:
            #TODO: unit variance and zero mean
            new_w = new_w / T.min(T.abs_(new_w))
        updates.append((self.velocity,velocity))
        return new_w

    def serialize(self):
        return 'SGD'

class FProp(UpdateRule):

    yaml_tag = u'!FProp'

    def __new__(cls):
        instance = super(FProp,cls).__new__(cls)
        common.toupee_global_instance.add_epoch_hook(lambda x: instance.epoch_hook(x))
        common.toupee_global_instance.add_reset_hook(lambda x: instance.reset(x))
        return instance

    def reset(self,updates):
        if 'momentum' not in self.__dict__:
            self.momentum = 0.
        if 'momentum_decay' not in self.__dict__:
            self.momentum_decay = 1.
        self.curr_momentum = sharedX(self.momentum)

    def epoch_hook(self,updates):
        updates.append((self.curr_momentum,self.curr_momentum * self.momentum_decay))

    def __init__(self):
        self.eta_plus  = 1.5
        self.eta_minus = 0.25
        self.max_delta = 50
        self.min_delta = 1e-8

    def __call__(self, param, learning_rate, gparam, mask, updates,
                 current_cost, previous_cost):
        ones_array = numpy.ones(param.shape.eval())
        previous_grad = sharedX(ones_array,borrow=True)
        delta = sharedX(self.min_delta * ones_array,borrow=True)
        previous_inc = sharedX(numpy.zeros(param.shape.eval()),borrow=True)
        zero = T.zeros_like(param)
        one = T.ones_like(param)
        change = previous_grad * gparam
        q = sharedX(ones_array,borrow=True)
        cost_increased = 0 #T.gt(current_cost,previous_cost)
        masked_gparam = mask * gparam
        masked =  T.eq(mask * gparam,0.)
        change_above_zero = T.gt(change,0.)
        change_below_zero = T.lt(change,0.)

        def mask_filter(m,u):
            return T.switch(masked, m, u)

        new_delta = T.clip(
                T.switch(
                    change_above_zero,
                    delta * self.eta_plus,
                    T.switch(
                        change_below_zero,
                        delta * self.eta_minus,
                        delta
                    )
                ),
                self.min_delta,
                self.max_delta
        )
        new_previous_grad = mask_filter(
            previous_grad,
            T.switch(change_below_zero, zero, gparam)
        )

        self.ms = sharedX(numpy.zeros(param.shape.eval()),borrow=True)
        ms = 0.9 * self.ms + 0.1 * (gparam ** 2)
        step = new_delta * gparam / T.sqrt(ms + 1.0e-11)

        unmasked_inc = T.switch(change_below_zero, zero, step)
        normal_inc = mask_filter(zero,unmasked_inc)

        inc = T.switch(cost_increased, previous_inc, normal_inc)
        d_w = T.switch(cost_increased, -previous_inc / (2 ** q), normal_inc)
        new_q = T.switch(cost_increased, q + 1, 1)

        updates.append((previous_grad,new_previous_grad))
        updates.append((delta,new_delta))
        updates.append((previous_inc,inc))
        updates.append((q,new_q))
        updates.append((self.ms,ms))
        return param + d_w * mask


class RMSProp(UpdateRule):

    yaml_tag = u'!RMSProp'

    def __new__(cls):
        instance = super(RMSProp,cls).__new__(cls)
        common.toupee_global_instance.add_epoch_hook(lambda x: instance.epoch_hook(x))
        common.toupee_global_instance.add_reset_hook(lambda x: instance.reset(x))
        return instance

    def reset(self,updates):
        if 'momentum' not in self.__dict__:
            self.momentum = 0.
        if 'momentum_decay' not in self.__dict__:
            self.momentum_decay = 1.
        self.curr_momentum = sharedX(self.momentum)

    def epoch_hook(self,updates):
        updates.append((self.curr_momentum,self.curr_momentum * self.momentum_decay))

    def __init__(self):
        pass

    def __call__(self, param, learning_rate, gparam, mask, updates,
                 current_cost, previous_cost):
        self.velocity = sharedX(numpy.zeros(param.shape.eval()),borrow=True)
        self.ms = sharedX(numpy.zeros(param.shape.eval()),borrow=True)
        ms = 0.9 * self.ms + 0.1 * (gparam ** 2)
        grad_scaled = gparam / T.sqrt(ms + 1.0e-11)
        if self.momentum:
            velocity = (self.velocity * self.curr_momentum - learning_rate.get() * grad_scaled)
        else:
            velocity = - learning_rate.get() * grad_scaled
        new_w = param + velocity * mask
        updates.append((self.velocity,velocity))
        updates.append((self.ms,ms))
        return new_w

    def serialize(self):
        return 'RMSProp'


class UProp(UpdateRule):

    yaml_tag = u'!UProp'

    def __new__(cls):
        instance = super(UProp,cls).__new__(cls)
        common.toupee_global_instance.add_epoch_hook(lambda x: instance.epoch_hook(x))
        common.toupee_global_instance.add_reset_hook(lambda x: instance.reset(x))
        return instance

    def reset(self,updates):
        if 'momentum' not in self.__dict__:
            self.momentum = 0.
        if 'momentum_decay' not in self.__dict__:
            self.momentum_decay = 1.
        self.curr_momentum = sharedX(self.momentum)

    def epoch_hook(self,updates):
        updates.append((self.curr_momentum,self.curr_momentum * self.momentum_decay))

    def __init__(self):
        self.eta_plus = 1.1
        self.eta_minus = 0.9

    def __call__(self, param, learning_rate, gparam, mask, updates,
                 current_cost, previous_cost):
        self.velocity = sharedX(numpy.zeros(param.shape.eval()),borrow=True)
        self.acceleration = sharedX(numpy.ones(param.shape.eval()),borrow=True)
        self.acceleration_mean = sharedX(numpy.ones(param.shape.eval()),borrow=True)
        self.ms = sharedX(numpy.zeros(param.shape.eval()),borrow=True)
        previous_grad = sharedX(numpy.ones(param.shape.eval()),borrow=True)
        previous_delta_w = sharedX(numpy.ones(param.shape.eval()),borrow=True)
        zero = T.zeros_like(param)

        change = previous_grad * gparam
        change_below_zero = T.lt(change,0.)
        change_above_zero = T.gt(change,0.)
        cost_increased = T.gt(current_cost,previous_cost)

        acceleration = T.switch(
                        change_below_zero,
                        self.acceleration * self.eta_minus,
                        T.switch(change_above_zero,
                            self.acceleration * self.eta_plus,
                            self.acceleration
                        )
                       )
        acceleration = T.clip(acceleration,0.1,10.0)
        acceleration_mean = 0.9 * self.acceleration_mean + 0.1 * acceleration
#        acceleration = theano.printing.Print("ACC")(acceleration)
        ms = 0.9 * self.ms + 0.1 * (gparam ** 2)
        grad_scaled = gparam / T.sqrt(ms + 1.0e-11)
        if self.momentum:
            velocity = (self.velocity * self.curr_momentum -
                        learning_rate.get() * grad_scaled)
        else:
            velocity = - learning_rate.get() * grad_scaled
        learning_rate = acceleration / acceleration_mean
        delta_w = velocity * mask * learning_rate
        new_w = param + delta_w
        updates.append((self.velocity,velocity))
        updates.append((self.ms,ms))
        updates.append((self.acceleration,acceleration))
        updates.append((self.acceleration_mean, acceleration))
        updates.append((previous_grad,gparam))
        updates.append((previous_delta_w,delta_w))
        return new_w

    def serialize(self):
        return 'UProp'


class RPropVariant(UpdateRule):

    def __init__(self):
        self.eta_plus = 1.2
        self.eta_minus = 0.5
        self.max_delta=50
        self.min_delta=1e-6

    def __init__(self,eta_plus,eta_minus,max_delta,min_delta):
        self.eta_plus = eta_plus
        self.eta_minus = eta_minus
        self.max_delta = max_delta
        self.min_delta = min_delta

    def __repr__(self):
        return "%s(eta_plus=%r,eta_minus=%r,max_delta=%r,min_delta=%r)" % (
                self.__class__.__name__, self.eta_plus,self.eta_minus,
                self.max_delta,self.min_delta)
                
class OldRProp(RPropVariant):

    yaml_tag = u'!OldRProp'
    def __call__(self, param, learning_rate, gparam, mask, updates,
                 current_cost, previous_cost):
        previous_grad = sharedX(numpy.ones(param.shape.eval()),borrow=True)
        delta = sharedX(self.min_delta * numpy.ones(param.shape.eval()),borrow=True)
        previous_inc = sharedX(numpy.zeros(param.shape.eval()),borrow=True)
        zero = T.zeros_like(param)
        one = T.ones_like(param)
        change = previous_grad * gparam

        new_delta = T.clip(
                T.switch(
                    T.gt(change,0.),
                    delta * self.eta_plus,
                    T.switch(
                        T.lt(change,0.),
                        delta * self.eta_minus,
                        delta
                    )
                ),
                self.min_delta,
                self.max_delta
        )
        new_previous_grad = T.switch(
                T.gt(change,0.),
                gparam,
                T.switch(
                    T.lt(change,0.),
                    zero,
                    gparam
                )
        )
        inc = T.switch(
                T.gt(change,0.),
                - T.sgn(gparam) * new_delta,
                T.switch(
                    T.lt(change,0.),
                    zero,
                    - T.sgn(gparam) * new_delta
                )
        )

        updates.append((previous_grad,new_previous_grad))
        updates.append((delta,new_delta))
        updates.append((previous_inc,inc))
        return param + inc * mask


class RProp(RPropVariant):

    yaml_tag = u'!RProp'

    def __new__(cls):
        instance = super(RProp,cls).__new__(cls)
        common.toupee_global_instance.add_epoch_hook(lambda x: instance.epoch_hook(x))
        common.toupee_global_instance.add_reset_hook(lambda x: instance.reset(x))
        return instance

    def __init__(self):
        self.eta_plus = 1.01
        self.eta_minus = 0.1
        self.max_delta=5
        self.min_delta=1e-3

    def reset(self,updates):
        if 'momentum' not in self.__dict__:
            self.momentum = 0.
        if 'momentum_decay' not in self.__dict__:
            self.momentum_decay = 1.
        self.momentum_var = sharedX(self.momentum)

    def epoch_hook(self,updates):
        updates.append((self.momentum_var,self.momentum_var * self.momentum_decay))

    def __call__(self, param, learning_rate, gparam, mask, updates,
                 current_cost, previous_cost):
        if 'momentum' not in self.__dict__:
            self.momentum = 0.
        if 'momentum_decay' not in self.__dict__:
            self.momentum_decay = 1.
        self.momentum_var = sharedX(self.momentum)
        ones_array = numpy.ones(param.shape.eval())
        previous_grad = sharedX(ones_array,borrow=True)
        delta = sharedX(self.min_delta * ones_array,borrow=True)
        previous_inc = sharedX(numpy.zeros(param.shape.eval()),borrow=True)
        velocity = sharedX(numpy.zeros(param.shape.eval()),borrow=True)
        zero = T.zeros_like(param)
        one = T.ones_like(param)
        change = previous_grad * gparam
        q = sharedX(ones_array,borrow=True)
        cost_increased = T.gt(current_cost,previous_cost)
        masked_gparam = mask * gparam
        masked =  T.eq(mask * gparam,0.)
        change_above_zero = T.gt(change,0.)
        change_below_zero = T.lt(change,0.)

        def mask_filter(m,u):
            return T.switch(masked, m, u)

        new_delta = T.clip(
                T.switch(
                    change_above_zero,
                    delta * self.eta_plus,
                    T.switch(
                        change_below_zero,
                        delta * self.eta_minus,
                        delta
                    )
                ),
                self.min_delta,
                self.max_delta
        )
        new_previous_grad = mask_filter(
            previous_grad,
            T.switch(change_below_zero, zero, gparam)
        )
        step = - T.sgn(gparam) * new_delta
        unmasked_inc = T.switch(change_below_zero, zero, step)
        d_w = mask_filter(zero,unmasked_inc)

        #Momentum
        new_velocity = (velocity * self.momentum_var + d_w)

        updates.append((velocity,new_velocity))
        updates.append((previous_grad,new_previous_grad))
        updates.append((delta,new_delta))
        updates.append((previous_inc,d_w))
        return param + new_velocity * mask

    def serialize(self):
        return 'RProp'

class iRPropPlus(RPropVariant):

    yaml_tag = u'!iRProp+'
    def __init__(self):
        self.eta_plus = 1.5
        self.eta_minus = 0.25
        self.max_delta=500
        self.min_delta=1e-8

    def __call__(self, param, learning_rate, gparam, mask, updates,
                 current_cost, previous_cost):
        previous_grad = sharedX(numpy.ones(param.shape.eval()),borrow=True)
        delta = sharedX(self.min_delta * numpy.ones(param.shape.eval()),borrow=True)
        previous_inc = sharedX(numpy.zeros(param.shape.eval()),borrow=True)
        zero = T.zeros_like(param)
        one = T.ones_like(param)
        change = previous_grad * gparam

        new_delta = T.clip(
                T.switch(
                    T.eq(gparam,0.),
                    delta,
                    T.switch(
                        T.gt(change,0.),
                        delta * self.eta_plus,
                        T.switch(
                            T.lt(change,0.),
                            delta * self.eta_minus,
                            delta
                        )
                    )
                ),
                self.min_delta,
                self.max_delta
        )
        new_previous_grad = T.switch(
                T.eq(mask * gparam,0.),
                previous_grad,
                T.switch(
                    T.gt(change,0.),
                    gparam,
                    T.switch(
                        T.lt(change,0.),
                        zero,
                        gparam
                    )
                )
        )
        inc = T.switch(
                T.eq(mask * gparam,0.),
                zero,
                T.switch(
                    T.gt(change,0.),
                    - T.sgn(gparam) * new_delta,
                    T.switch(
                        T.lt(change,0.),
                        T.switch(T.gt(current_cost,previous_cost),
                            - previous_inc,
                            zero
                        ),
                        - T.sgn(gparam) * new_delta
                    )
                )
        )

        updates.append((previous_grad,new_previous_grad))
        updates.append((delta,new_delta))
        updates.append((previous_inc,inc))
        return param + inc * mask

class ARProp(RPropVariant):

    yaml_tag = u'!ARProp'
    def __init__(self):
        self.eta_plus = 1.5
        self.eta_minus = 0.25
        self.max_delta=500
        self.min_delta=1e-8

    def __call__(self, param, learning_rate, gparam, mask, updates,
                 current_cost, previous_cost):
        ones_array = numpy.ones(param.shape.eval())
        previous_grad = sharedX(ones_array,borrow=True)
        delta = sharedX(self.min_delta * ones_array,borrow=True)
        previous_inc = sharedX(numpy.zeros(param.shape.eval()),borrow=True)
        zero = T.zeros_like(param)
        one = T.ones_like(param)
        change = previous_grad * gparam
        q = sharedX(ones_array,borrow=True)
        cost_increased = T.gt(current_cost,previous_cost)
        masked_gparam = mask * gparam
        masked =  T.eq(mask * gparam,0.)
        change_above_zero = T.gt(change,0.)
        change_below_zero = T.lt(change,0.)

        def mask_filter(m,u):
            return T.switch(masked, m, u)

        new_delta = T.clip(
                T.switch(
                    change_above_zero,
                    delta * self.eta_plus,
                    T.switch(
                        change_below_zero,
                        delta * self.eta_minus,
                        delta
                    )
                ),
                self.min_delta,
                self.max_delta
        )
        new_previous_grad = mask_filter(
            previous_grad,
            T.switch(change_below_zero, zero, gparam)
        )
        step = - T.sgn(gparam) * new_delta
        unmasked_inc = T.switch(change_below_zero, zero, step)
        normal_inc = mask_filter(zero,unmasked_inc)

        inc = T.switch(cost_increased, previous_inc, normal_inc)
        d_w = T.switch(cost_increased, -previous_inc / (2 ** q), normal_inc)
        new_q = T.switch(cost_increased, q + 1, 1)

        updates.append((previous_grad,new_previous_grad))
        updates.append((delta,new_delta))
        updates.append((previous_inc,inc))
        updates.append((q,new_q))
        return param + d_w * mask


class DRProp(RPropVariant):

    yaml_tag = u'!DRProp'

    def __new__(cls):
        instance = super(DRProp,cls).__new__(cls)
        common.toupee_global_instance.add_epoch_hook(lambda x: instance.epoch_hook(x))
        common.toupee_global_instance.add_reset_hook(lambda x: instance.reset(x))
        return instance

    def __init__(self):
        self.eta_plus = 1.5
        self.eta_minus = 0.25
        self.max_delta=500
        self.start_min_delta=1e-3
        self.stop_min_delta=1e-8
        self.multiplier_min_delta=0.9

    def reset(self,updates):
        if 'momentum' not in self.__dict__:
            self.momentum = 0.
        if 'momentum_decay' not in self.__dict__:
            self.momentum_decay = 1.
        self.momentum_var = sharedX(self.momentum)
        self.min_delta = sharedX(self.start_min_delta)

    def epoch_hook(self,updates):
        new_min = T.clip(self.min_delta * self.multiplier_min_delta,
                self.stop_min_delta, self.start_min_delta)
        updates.append((self.min_delta,new_min))
        updates.append((self.momentum_var,self.momentum_var * self.momentum_decay))

    def __call__(self, param, learning_rate, gparam, mask, updates,
                 current_cost, previous_cost):
        if 'momentum' not in self.__dict__:
            self.momentum = 0.
        if 'momentum_decay' not in self.__dict__:
            self.momentum_decay = 1.
        self.momentum_var = sharedX(self.momentum)
        ones_array = numpy.ones(param.shape.eval())
        previous_grad = sharedX(ones_array,borrow=True)
        delta = sharedX(self.start_min_delta * ones_array,borrow=True)
        previous_inc = sharedX(numpy.zeros(param.shape.eval()),borrow=True)
        velocity = sharedX(numpy.zeros(param.shape.eval()),borrow=True)
        zero = T.zeros_like(param)
        one = T.ones_like(param)
        change = previous_grad * gparam
        q = sharedX(ones_array,borrow=True)
        cost_increased = T.gt(current_cost,previous_cost)
        masked_gparam = mask * gparam
        masked =  T.eq(mask * gparam,0.)
        change_above_zero = T.gt(change,0.)
        change_below_zero = T.lt(change,0.)
        def mask_filter(m,u):
            return T.switch(masked, m, u)

        new_delta = T.clip(
                T.switch(
                    change_above_zero,
                    delta * self.eta_plus,
                    T.switch(
                        change_below_zero,
                        delta * self.eta_minus,
                        delta
                    )
                ),
                self.min_delta,
                self.max_delta
        )
        new_previous_grad = mask_filter(
            previous_grad,
            T.switch(change_below_zero, zero, gparam)
        )
        step = - T.sgn(gparam) * new_delta
        unmasked_inc = T.switch(change_below_zero, zero, step)
        d_w = mask_filter(zero,unmasked_inc)

        #Momentum
        new_velocity = (velocity * self.momentum_var + d_w)

        updates.append((velocity,new_velocity))
        updates.append((previous_grad,new_previous_grad))
        updates.append((delta,new_delta))
        updates.append((previous_inc,d_w))
        new_w = param + new_velocity * mask
        new_w = new_w
        return new_w


class ADRProp(RPropVariant):

    yaml_tag = u'!ADRProp'

    def __new__(cls):
        instance = super(ADRProp,cls).__new__(cls)
        common.toupee_global_instance.add_epoch_hook(lambda x: instance.epoch_hook(x))
        common.toupee_global_instance.add_reset_hook(lambda x: instance.reset(x))
        return instance

    def __init__(self):
        self.eta_plus = 1.5
        self.eta_minus = 0.25
        self.max_delta=500
        self.start_min_delta=1e-3
        self.stop_min_delta=1e-8
        self.multiplier_min_delta=0.9

    def reset(self,updates):
        self.min_delta = sharedX(self.start_min_delta)
        if 'momentum' not in self.__dict__:
            self.momentum = 0.
        if 'momentum_decay' not in self.__dict__:
            self.momentum_decay = 1.
        self.momentum_var = sharedX(self.momentum)

    def epoch_hook(self,updates):
        new_min = T.clip(self.min_delta * self.multiplier_min_delta,
                self.stop_min_delta, self.start_min_delta)
        updates.append((self.min_delta,new_min))
        updates.append((self.momentum_var,self.momentum_var * self.momentum_decay))

    def __call__(self, param, learning_rate, gparam, mask, updates,
                 current_cost, previous_cost):
        if 'momentum' not in self.__dict__:
            self.momentum = 0.
        if 'momentum_decay' not in self.__dict__:
            self.momentum_decay = 1.
        self.momentum_var = sharedX(self.momentum)
        ones_array = numpy.ones(param.shape.eval())
        previous_grad = sharedX(ones_array,borrow=True)
        delta = sharedX(self.start_min_delta * ones_array,borrow=True)
        previous_inc = sharedX(numpy.zeros(param.shape.eval()),borrow=True)
        velocity = sharedX(numpy.zeros(param.shape.eval()),borrow=True)
        zero = T.zeros_like(param)
        one = T.ones_like(param)
        change = previous_grad * gparam
        q = sharedX(ones_array,borrow=True)
        cost_increased = T.gt(current_cost,previous_cost)
        masked_gparam = mask * gparam
        masked =  T.eq(mask * gparam,0.)
        change_above_zero = T.gt(change,0.)
        change_below_zero = T.lt(change,0.)

        def mask_filter(m,u):
            return T.switch(masked, m, u)

        new_delta = T.clip(
                T.switch(
                    change_above_zero,
                    delta * self.eta_plus,
                    T.switch(
                        change_below_zero,
                        delta * self.eta_minus,
                        delta
                    )
                ),
                self.min_delta,
                self.max_delta
        )
        new_previous_grad = mask_filter(
            previous_grad,
            T.switch(change_below_zero, zero, gparam)
        )
        step = - T.sgn(gparam) * new_delta
        unmasked_inc = T.switch(change_below_zero, zero, step)
        normal_inc = mask_filter(zero,unmasked_inc)

        #the ARProp bits
        inc = T.switch(cost_increased, previous_inc, normal_inc)
        d_w = T.switch(cost_increased, -previous_inc / (2 ** q), normal_inc)
        new_q = T.switch(cost_increased, q + 1, 1)
        
        #Momentum
        new_velocity = (velocity * self.momentum_var + d_w)

        updates.append((velocity,new_velocity))
        updates.append((previous_grad,new_previous_grad))
        updates.append((delta,new_delta))
        updates.append((previous_inc,inc))
        updates.append((q,new_q))
        return param + new_velocity * mask
