# -*- coding: utf-8 -*-
from __future__ import unicode_literals

import json
import logging
import time
from datetime import datetime, time, timedelta
from socket import AF_INET

import lib.utils as utils
import netifaces as ni
from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.core.urlresolvers import reverse
from django.http import Http404, HttpResponse, JsonResponse
from django.shortcuts import render
from django.template import loader
from django.template.defaultfilters import date as _localdate
from django.utils.timezone import now as django_now
from django.utils.translation import ugettext_lazy as _
from django.views.decorators.http import require_http_methods, require_POST
from lib import jobs
from www.templatetags.base_extras import get_device_name

from . import jobs as devicejobs
from .models import DeviceEntry

# Get an instance of a logger
logger = logging.getLogger('uprilogger')


def get_entries():
    gateway = None
    try:
        gateway = ni.gateways()['default'][AF_INET][0]
    except KeyError:
        pass

    return sorted(
        DeviceEntry.objects.filter(last_seen__gte=datetime.now() - timedelta(weeks=1), mac__regex=r'([0-9a-f]:?){12}')
        .exclude(ip=gateway), key=lambda x: get_device_name(x).upper()
    )


@require_http_methods(["GET", "POST"])
@login_required
def get_devices(request):
    return render(request, "devices.html", {
        'messagestore': jobs.get_messages(),
        'devices': get_entries(),
    })


@require_POST
@login_required
def refresh_devices(request):
    try:
        utils.exec_upri_config('parse_user_agents')
    except utils.AnsibleError as ae:
        logger.exception(ae)

    devices = get_entries()
    response = [
        {
            'slug': dev.slug,
            'mode': dev.mode,
            'mode_url': reverse('upri_devices_mode'),
            'name_url': reverse('upri_device_name', kwargs={'slug': dev.slug}),
            'name': get_device_name(dev),
            'changing': dev.changing
        } for dev in devices
    ]

    return JsonResponse(response, safe=False)


@login_required
@require_POST
def set_device_mode(request):
    mode = request.POST.get('mode', None)
    try:
        device = DeviceEntry.objects.get(slug=request.POST.get('dev_id', None))
    except DeviceEntry.DoesNotExist:
        device = None
    device.changing = True
    device.save()
    jobs.queue_job(devicejobs.toggle_device_mode, (mode, device))

    return render(request, "modal.html", {"message": True, "refresh_url": reverse('upri_devices')})


@login_required
@require_http_methods(["GET", "POST"])
def change_name(request, slug):
    if request.method == 'POST':
        name_mode = request.POST.get("changeName", None)
        suggestion = request.POST.get("suggestion", None)
        chosen_name = request.POST.get("chosenName", None)

        if not name_mode or name_mode not in ("suggestion", "chosenName"):
            raise Http404("invalid request")

        if name_mode == "suggestion":
            if not suggestion:
                raise Http404("invalid request")
            else:
                dev = DeviceEntry.objects.get(slug=slug)
                dev.chosen_name = suggestion
                dev.save()
        elif name_mode == "chosenName":
            if not chosen_name:
                temp = loader.get_template('name_modal.html')
                message = {
                    "device": DeviceEntry.objects.get(slug=slug),
                    "href": reverse('upri_device_name', kwargs={'slug': slug}),
                    "error": _("Der gewählte Name darf nicht leer sein")
                }
                return HttpResponse(temp.render(message, request), content_type='text/html; charset=utf-8', status=404)
            else:
                dev = DeviceEntry.objects.get(slug=slug)
                dev.chosen_name = chosen_name
                dev.save()

        # return render(request, "devices.html", {
        #     'messagestore': jobs.get_messages(),
        #     'devices': get_entries(),
        # })
        return HttpResponse(dev.chosen_name, content_type='text/html; charset=utf-8')
    else:
        return render(
            request, "name_modal.html", {"device": DeviceEntry.objects.get(slug=slug),
                                         "href": reverse('upri_device_name', kwargs={'slug': slug})}
        )


@login_required
@require_POST
def get_device_status(request, slug):
    try:
        dev = DeviceEntry.objects.get(slug=slug)
    except DeviceEntry.DoesNotExist:
        res = None
    else:
        res = utils.exec_upri_config("check_device", dev.ip)
        if bool(res):
            # update last_seen date
            dev.last_seen = django_now()
            dev.save()

    return JsonResponse({slug: bool(res)})


@login_required
@require_POST
def changing_devices(request):
    devices = DeviceEntry.objects.filter(changing=True)
    return JsonResponse([dev.slug for dev in devices], safe=False)


@login_required
@require_POST
def device_entry(request):
    return render(request, "device_entry.html", {
        'messagestore': jobs.get_messages(),
        'devices': {
            'mode': None,
            'slug': "",
            'changing': ''
        },
    })


@require_http_methods(["GET", "POST"])
@login_required
def single_device_template(request):
    return render(request, "device_entry.html")


@login_required
def fail(request):
    # if not settings.DEBUG:
    #     raise Http404()

    jobs.queue_job(devicejobs.fail_dummy, ("", ))
    return HttpResponse(status=200)
