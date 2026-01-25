# Copyright 2026 EcoFuture Technology Services LLC and contributors
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

import os

import psutil


reload = False
preload_app = True
timeout = 120
threads = 6
error_logfile = '-'
capture_output = True
worker_tmp_dir = '/dev/shm'
forwarded_allow_ips = '*'
max_requests = 50000
max_requests_jitter = int(max_requests / 10) + 1
worker_class = 'uvicorn.workers.UvicornWorker'
workers = int(os.getenv('_BS_APP_GUNICORN_WORKERS', psutil.cpu_count()))
bind = ['0.0.0.0:' + os.getenv('BS_APP_PORT', 8080)]
