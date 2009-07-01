from __future__ import with_statement
import time, urllib, re, os
import logging as log
import email.utils
import threading
import xml.sax.saxutils
import shutil
try:
    import simplejson as json
except ImportError:
    import json
from smtplib import SMTP
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from analyze import TalosAnalyzer, PerfDatum

def avg(l):
    return sum(l) / float(len(l))

def send_msg(fromaddr, subject, msg, addrs, html=None):
    s = SMTP()
    s.connect()

    for addr in addrs:
        if html:
            m = MIMEMultipart('alternative')
            m.attach(MIMEText(msg))
            m.attach(MIMEText(html, "html"))
        else:
            m = MIMEText(msg)
        m['date'] = email.utils.formatdate()
        m['to'] = addr
        m['subject'] = subject

        s.sendmail(fromaddr, [addr], m.as_string())
    s.quit()

class AnalysisRunner:
    def __init__(self, options, config):
        self.options = options
        self.config = config

        if not options.branches:
            options.branches = [s for s in config.sections() if s != "main"]

        if options.output is None or options.output == "-":
            self.output = sys.stdout
        else:
            self.output = open(options.output, "w")

        log.basicConfig(level=options.verbosity, format="%(asctime)s %(message)s")

        self.loadWarningHistory()
        self.loadPushDates()

        self.all_data = []
        self.fore_window = config.getint('main', 'fore_window')
        self.back_window = config.getint('main', 'back_window')
        self.threshold = config.getfloat('main', 'threshold')
        self.machine_threshold = config.getfloat('main', 'machine_threshold')
        self.machine_history_size = config.getint('main', 'machine_history_size')

        if config.get('main', 'method') == 'graphapi':
            from analyze_graphapi import GraphAPISource
            graph_url = config.get('main', 'base_graph_url')
            self.source = GraphAPISource("%(graph_url)s/api" % locals())
        else:
            import analyze_db as source
            self.source = source

        self.lock = threading.RLock()

    def loadWarningHistory(self):
        # Stop warning about stuff from a long time ago
        fn = self.config.get('main', 'warning_history')
        cutoff = self.options.start_time
        try:
            if not os.path.exists(fn):
                self.warning_history = {}
                return
            self.warning_history = json.load(open(fn))
            # Purge old warnings
            for branch, oses in self.warning_history.items():
                if branch in ('inactive_machines', 'bad_machines'):
                    continue
                for os_name, tests in oses.items():
                    for test_name, values in tests.items():
                        for d in values[:]:
                            buildid, timestamp = d
                            if timestamp < cutoff:
                                log.debug("Removing warning %s since it's before cutoff (%s)", d, cutoff)
                                values.remove(d)
                            else:
                                # Convert to tuples
                                values.remove(d)
                                values.append((buildid, timestamp))

                        if not values:
                            log.debug("Removing empty warning list %s %s %s", branch, os_name, test_name)
                            del tests[test_name]
                    if not tests:
                        log.debug("Removing empty os list %s %s", branch, os_name)
                        del oses[os_name]
                if not oses:
                    log.debug("Removing empty branch list %s", branch)
                    del self.warning_history[branch]
        except:
            log.exception("Couldn't load warnings from %s", fn)
            self.warning_history = {}

    def saveWarningHistory(self):
        fn = self.config.get('main', 'warning_history')
        json.dump(self.warning_history, open(fn, "w"), indent=2, sort_keys=True)

    def loadPushDates(self):
        fn = self.config.get('main', 'pushdates')
        try:
            if not os.path.exists(fn):
                self.pushdates = {}
                return
            self.pushdates = json.load(open(fn))
        except:
            log.exception("Couldn't load push dates from %s", fn)
            self.pushdates = {}

    def savePushDates(self):
        fn = self.config.get('main', 'pushdates')
        json.dump(self.pushdates, open(fn, "w"), indent=2, sort_keys=True)

    def getPushDates(self, branch, changesets):
        retval = {}
        to_query = []
        if branch not in self.pushdates:
            with self.lock:
                self.pushdates[branch] = {}
        for c in changesets:
            if c in self.pushdates[branch]:
                retval[c] = self.pushdates[branch][c]
            else:
                to_query.append(c)

        if len(to_query) > 0:
            repo_path = self.config.get(branch, 'repo_path')
            log.debug("Fetching %i changesets", len(to_query))
            for i in range(0, len(to_query), 50):
                chunk = to_query[i:i+50]
                changesets = ["changeset=%s" % c for c in chunk]
                base_url = self.config.get('main', 'base_hg_url')
                url = "%s/%s/json-pushes?%s" % (base_url, repo_path, "&".join(changesets))
                raw_data = urllib.urlopen(url).read()
                try:
                    data = json.loads(raw_data)
                except:
                    log.exception("Error parsing %s", raw_data)
                    raise
                with self.lock:
                    if branch not in self.pushdates:
                        self.pushdates[branch] = {}
                    if isinstance(data, dict):
                        for entry in data.values():
                            for changeset in entry['changesets']:
                                self.pushdates[branch][changeset[:12]] = entry['date']
                                retval[changeset[:12]] = entry['date']

        return retval

    def updateTimes(self, branch, data):
        # We want to fetch the changesets so we can order the data points by
        # push time, rather than by test time
        changesets = set(d.revision for d in data)

        dates = self.getPushDates(branch, changesets)

        for d in data:
            rev = dates.get(d.revision, None)
            if rev:
                d.time = rev

    def makeChartUrl(self, series, d=None):
        test_params = []
        machine_ids = self.source.getMachinesForTest(series)
        for machine_id in machine_ids:
            test_params.append(dict(test=series.test_id, branch=series.branch_id, machine=machine_id))
        test_params = json.dumps(test_params, separators=(",",":"))
        base_url = self.config.get('main', 'base_graph_url')
        if d is not None:
            start_time = d.timestamp - 24*3600
            end_time = d.timestamp + 24*3600
            return "%(base_url)s/graph.html#tests=%(test_params)s&sel=%(start_time)s,%(end_time)s" % locals()
        else:
            return "%(base_url)s/graph.html#tests=%(test_params)s" % locals()

    def makeHgUrl(self, branch, good_rev, bad_rev):
        base_url = self.config.get('main', 'base_hg_url')
        repo_path = self.config.get(branch, 'repo_path')
        if good_rev:
            hg_url = "%(base_url)s/%(repo_path)s/pushloghtml?fromchange=%(good_rev)s&tochange=%(bad_rev)s" % locals()
        else:
            hg_url = "%(base_url)s/%(repo_path)s/rev/%(bad_rev)s" % locals()
        return hg_url

    def formatMessage(self, state, series, good, bad, html=False):
        if state == "machine":
            good = bad.last_other

        branch_name = series.branch_name
        test_name = series.test_name
        os_name = series.os_name

        initial_value = good.value
        new_value = bad.value
        change = 100.0 * abs(new_value - initial_value) / float(initial_value)
        bad_build_time = datetime.fromtimestamp(bad.timestamp).strftime("%Y-%m-%d %H:%M:%S")
        good_build_time = datetime.fromtimestamp(good.timestamp).strftime("%Y-%m-%d %H:%M:%S")
        if new_value > initial_value:
            direction = "increase"
            reason = "Regression"
        else:
            direction = "decrease"
            reason = "Improvement"

        chart_url = self.makeChartUrl(series, bad)
        if good.revision:
            good_rev = "revision %s" % good.revision
        else:
            good_rev = "(unknown revision)"

        if bad.revision:
            bad_rev = "revision %s" % bad.revision
        else:
            bad_rev = "(unknown revision)"

        if good.revision and bad.revision:
            hg_url = "\n    " + self.makeHgUrl(branch_name, good.revision, bad.revision)
        else:
            hg_url = ""

        bad_build_id = bad.buildid
        good_build_id = good.buildid
        bad_machine_name = self.source.getMachineName(bad.machine_id)
        good_machine_name = self.source.getMachineName(good.machine_id)
        good_run_number = good.run_number
        bad_run_number = bad.run_number

        if state == "machine":
            reason = "Suspected machine issue (%s)" % bad_machine_name
            if not html:
                msg =  """\
%(reason)s: %(test_name)s %(direction)s %(change).2f%% on %(os_name)s %(branch_name)s
    Previous results:
        %(initial_value)s from build %(good_build_id)s of %(good_rev)s at %(good_build_time)s on %(good_machine_name)s
    New results:
        %(new_value)s from build %(bad_build_id)s of %(bad_rev)s at %(bad_build_time)s on %(bad_machine_name)s
    %(chart_url)s
""" % locals()
            else:
                chart_url_encoded = xml.sax.saxutils.quoteattr(chart_url)
                hg_url_encoded = xml.sax.saxutils.quoteattr(hg_url)
                msg =  """\
<p>%(reason)s: %(test_name)s <a href=%(chart_url_encoded)s>%(direction)s %(change).2f%%</a> on %(os_name)s %(branch_name)s</p>
<p>Previous results: %(initial_value)s from build %(good_build_id)s of %(good_rev)s at %(good_build_time)s on %(good_machine_name)s</p>
<p>New results: %(new_value)s from build %(bad_build_id)s of %(bad_rev)s at %(bad_build_time)s on %(bad_machine_name)s</p>

<p>Suspected checkin range: <a href=%(hg_url_encoded)s>from %(good_rev)s to %(bad_rev)s</a></p>
""" % locals()
        else:
            if not html:
                msg =  """\
%(reason)s: %(test_name)s %(direction)s %(change).2f%% on %(os_name)s %(branch_name)s
    Previous results:
        %(initial_value)s from build %(good_build_id)s of %(good_rev)s at %(good_build_time)s on %(good_machine_name)s run # %(good_run_number)s
    New results:
        %(new_value)s from build %(bad_build_id)s of %(bad_rev)s at %(bad_build_time)s on %(bad_machine_name)s run # %(bad_run_number)s
    %(chart_url)s%(hg_url)s
""" % locals()
            else:
                chart_url_encoded = xml.sax.saxutils.quoteattr(chart_url)
                hg_url_encoded = xml.sax.saxutils.quoteattr(hg_url)
                msg =  """\
<p>%(reason)s: %(test_name)s <a href=%(chart_url_encoded)s>%(direction)s %(change).2f%%</a> on %(os_name)s %(branch_name)s</p>
<p>Previous results: %(initial_value)s from build %(good_build_id)s of %(good_rev)s at %(good_build_time)s on %(good_machine_name)s run # %(good_run_number)s</p>
<p>New results: %(new_value)s from build %(bad_build_id)s of %(bad_rev)s at %(bad_build_time)s on %(bad_machine_name)s run # %(bad_run_number)s</p>

<p>Suspected checkin range: <a href=%(hg_url_encoded)s>from %(good_rev)s to %(bad_rev)s</a></p>
""" % locals()
        return msg

    def formatHTMLMessage(self, state, series, good, bad):
        return self.formatMessage(state, series, good, bad, html=True)

    def formatSubject(self, state, series, good, bad):
        if state == "machine":
            good = bad.last_other

        branch_name = series.branch_name
        test_name = series.test_name
        os_name = series.os_name

        initial_value = good.value
        new_value = bad.value
        change = 100.0 * abs(new_value - initial_value) / float(initial_value)
        bad_build_time = datetime.fromtimestamp(bad.timestamp).strftime("%Y-%m-%d %H:%M:%S")
        good_build_time = datetime.fromtimestamp(good.timestamp).strftime("%Y-%m-%d %H:%M:%S")
        if new_value > initial_value:
            direction = "increase"
            reason = "Regression"
        else:
            direction = "decrease"
            reason = "Improvement"
        if state == "machine":
            bad_machine_name = self.source.getMachineName(bad.machine_id)
            good_machine_name = self.source.getMachineName(good.machine_id)
            reason = "Suspected machine issue (%s)" % bad_machine_name
        return "Talos %(reason)s: %(test_name)s %(direction)s %(change).2f%% on %(os_name)s %(branch_name)s" % locals()

    def printWarning(self, series, d, state, last_good):
        if self.output:
            with self.lock:
                self.output.write(self.formatMessage(state, series, last_good, d))
                self.output.write("\n")
                self.output.flush()

    def emailWarning(self, series, d, state, last_good):
        addresses = []
        if state == 'regression' and self.config.has_option('main', 'regression_emails'):
            addresses.extend(self.config.get('main', 'regression_emails').split(","))

        if state == 'machine' and self.config.has_option('main', 'machine_emails'):
            addresses.extend(self.config.get('main', 'machine_emails').split(","))

        if addresses:
            addresses = [a.strip() for a in addresses]
            subject = self.formatSubject(state, series, last_good, d)
            msg = self.formatMessage(state, series, last_good, d)
            html = self.formatHTMLMessage(state, series, last_good, d)
            send_msg(self.config.get('main', 'from_email'), subject, msg, addresses, html)

    def outputJson(self):
        warnings = {}
        for s, d, state, skip, last_good in self.all_data:
            if state == "good" or last_good is None:
                continue

            if s.branch_name not in warnings:
               warnings[s.branch_name] = {}
            if s.os_name not in warnings[s.branch_name]:
                warnings[s.branch_name][s.os_name] = {}
            if s.test_name not in warnings[s.branch_name][s.os_name]:
                warnings[s.branch_name][s.os_name][s.test_name] = []

            warnings[s.branch_name][s.os_name][s.test_name].append(
                dict(type=state,
                    good=dict(
                        build_id=last_good.buildid,
                        machine_id=last_good.machine_id,
                        timestamp=last_good.timestamp,
                        time=last_good.time,
                        revision=last_good.revision,
                        value=last_good.value,
                        ),
                    bad=dict(
                        build_id=d.buildid,
                        machine_id=d.machine_id,
                        timestamp=d.timestamp,
                        time=d.time,
                        revision=d.revision,
                        value=d.value,
                        )))
        json_file = self.config.get('main', 'json')
        if not os.path.exists(os.path.dirname(json_file)):
            os.makedirs(os.path.dirname(json_file))
        json.dump(warnings, open(json_file, "w"), sort_keys=True)

    def outputDashboard(self):
        data = {}
        sevenDaysAgo = time.time() - 7*24*60*60
        importantTests = [t.strip() for t in self.config.get('dashboard', 'tests').split(",")]
        for s, d, state, skip, last_good in self.all_data:
            if d.time < sevenDaysAgo:
                continue

            if s.test_name not in importantTests:
                continue

            if s.branch_name not in data:
               data[s.branch_name] = {}

            # We want to merge the Tp3 (Memset) and Tp3 (RSS) results together
            # for the dashboard, since they're just different names for the
            # same thing on different platforms
            test_name = s.test_name
            if test_name == "Tp3 (Memset)":
                test_name = "Tp3 (RSS)"

            if test_name not in data[s.branch_name]:
                data[s.branch_name][test_name] = {'_testid': s.test_id}

            if s.os_name not in data[s.branch_name][test_name]:
                data[s.branch_name][test_name][s.os_name] = {
                        '_platformid': s.os_id,
                        '_graphURL':self.makeChartUrl(s)
                        }

            machine_name = self.source.getMachineName(d.machine_id)
            if machine_name not in data[s.branch_name][test_name][s.os_name]:
                data[s.branch_name][test_name][s.os_name][machine_name] = {
                        'results': [],
                        'stats': [],
                        }

            results = data[s.branch_name][test_name][s.os_name][machine_name]['results']
            results.append(d.time)
            results.append(d.value)
            values = [results[i+1] for i in range(0, len(results), 2)]
            data[s.branch_name][test_name][s.os_name][machine_name]['stats'] = [avg(values), max(values), min(values)]

        dirname = self.config.get('main', 'dashboard_dir')
        if not os.path.exists(dirname):
            # Copy in the rest of html
            shutil.copytree('html/dashboard', dirname)
            shutil.copytree('html/flot', '%s/flot' % dirname)
            shutil.copytree('html/jquery', '%s/jquery' % dirname)
        filename = os.path.join(dirname, 'testdata.js')
        fp = open(filename + ".tmp", "w")
        now = time.asctime()
        fp.write("// Generated at %s\n" % now)
        fp.write("gFetchTime = ")
        json.dump(now, fp, separators=(',',':'))
        fp.write(";\n")
        fp.write("var gData = ")
        # Hackity hack
        # Don't pretend we have double precision here
        # 8 digits of precision is plenty
        try:
            json.encoder.FLOAT_REPR = lambda f: "%.8g" % f
        except:
            pass
        json.dump(data, fp, separators=(',',':'), sort_keys=True)
        try:
            json.encoder.FLOAT_REPR = repr
        except:
            pass

        fp.write(";\n")
        fp.close()
        os.rename(filename + ".tmp", filename)

    def outputGraphs(self, series, series_data):
        all_data = []
        good_data = []
        regressions = []
        bad_machines = {}
        graph_dir = self.config.get('main', 'graph_dir')
        basename = "%s/%s-%s-%s" % (graph_dir,
                series.branch_name, series.os_name, series.test_name)

        for s, d, state, skip, last_good in series_data:
            graph_point = (d.time * 1000, d.value)
            all_data.append(graph_point)
            if state == "good":
                good_data.append(graph_point)
            elif state == "regression":
                regressions.append(graph_point)
            elif state == "machine":
                bad_machines.setdefault(d.machine_id, []).append(graph_point)

        log.debug("Creating graph %s", basename)

        graphs = []
        graphs.append({"label": "Value", "data": all_data})

        graphs.append({"label": "Smooth Value", "data": good_data, "color": "green"})
        graphs.append({"label": "Regressions", "color": "red", "data": regressions, "lines": {"show": False}, "points": {"show": True}})
        for machine_id, points in bad_machines.items():
            machine_name = self.source.getMachineName(machine_id)
            graphs.append({"label": "Bad Machines (%s)" % machine_name, "data": points, "lines": {"show": False}, "points": {"show": True}})

        graph_file = "%s.js" % basename
        html_file = "%s.html" % basename
        html_template = open("html/graph_template.html").read()

        test_name = series.test_name
        os_name = series.os_name
        branch_name = series.branch_name

        title = "Talos Regression Graph for %(test_name)s on %(os_name)s %(branch_name)s" % locals()

        html = html_template % dict(graph_file = os.path.basename(graph_file),
                title=title)
        if not os.path.exists(graph_dir):
            os.makedirs(graph_dir)
            # Copy in the rest of the HTML as well
            shutil.copytree('html/flot', '%s/flot' % graph_dir)

        open(html_file, "w").write(html)
        open(graph_file, "w").write("var graph_data = %s;" % json.dumps(graphs))

    def findInactiveMachines(self):
        machine_dates = {}
        for s, d, state, skip, last_good in self.all_data:
            if d.machine_id not in machine_dates:
                machine_dates[d.machine_id] = d.time
            else:
                machine_dates[d.machine_id] = max(machine_dates[d.machine_id], d.time)

        if "inactive_machines" not in self.warning_history:
            self.warning_history['inactive_machines'] = {}

        # Complain about anything that hasn't reported in 48 hours
        cutoff = time.time() - 48*3600

        addresses = []
        if self.config.has_option('main', 'machine_emails'):
            addresses.extend(self.config.get('main', 'machine_emails').split(","))

        for machine_id, t in machine_dates.items():
            if t < cutoff:
                machine_name = self.source.getMachineName(machine_id)

                # When did we last warn about this machine?
                if self.warning_history['inactive_machines'].get(machine_name, 0) < time.time() - 7*24*3600:
                    # If it was over a week ago, then send another warning
                    self.warning_history['inactive_machines'][machine_name] = time.time()

                    subject = "Inactive Talos machine: %s" % machine_name
                    msg = "Talos machine %s hasn't reported any results since %s" % (machine_name, time.ctime(t))

                    self.output.write(msg)
                    self.output.write("\n")
                    self.output.flush()

                    if addresses:
                        send_msg(self.config.get('main', 'from_email'), subject, msg, addresses)

    def handleData(self, series, d, state, skip, last_good):
        if not skip and state != "good" and not self.options.catchup and last_good is not None:
            # Notify people of the warnings
            self.printWarning(series, d, state, last_good)
            self.emailWarning(series, d, state, last_good)

    def handleSeries(self, s):
        if self.config.has_option('os', s.os_name):
            s.os_name = self.config.get('os', s.os_name)
        log.info("Processing %s %s %s", s.branch_name, s.os_name, s.test_name)
        # Get all the test data for all machines running this combination
        data = self.source.getTestData(s, options.start_time)

        self.updateTimes(s.branch_name, data)

        a = TalosAnalyzer()
        a.addData(data)

        analysis_gen = a.analyze_t(self.back_window, self.fore_window,
                self.threshold, self.machine_threshold,
                self.machine_history_size)

        with self.lock:
            if s.branch_name not in self.warning_history:
                self.warning_history[s.branch_name] = {}
            if s.os_name not in self.warning_history[s.branch_name]:
                self.warning_history[s.branch_name][s.os_name] = {}
            if s.test_name not in self.warning_history[s.branch_name][s.os_name]:
                self.warning_history[s.branch_name][s.os_name][s.test_name] = []
            warnings = self.warning_history[s.branch_name][s.os_name][s.test_name]

        last_good = None
        last_err = None
        last_err_good = None
        #cutoff = self.options.start_time
        cutoff = time.time() - 7*24*3600
        series_data = []
        for d, state in analysis_gen:
            skip = False
            if d.timestamp < cutoff:
                continue

            if state != "good":
                # Skip warnings about regressions we've already
                # warned people about
                with self.lock:
                    if (d.buildid, d.timestamp) in warnings:
                        skip = True
                    else:
                        warnings.append((d.buildid, d.timestamp))
                        if state == "machine":
                            machine_name = self.source.getMachineName(d.machine_id)
                            if 'bad_machines' not in self.warning_history:
                                self.warning_history['bad_machines'] = {}
                            # When did we last warn about this machine?
                            if self.warning_history['bad_machines'].get(machine_name, 0) > time.time() - 7*24*3600:
                                skip = True
                            else:
                                # If it was over a week ago, then send another warning
                                self.warning_history['bad_machines'][machine_name] = time.time()

                if not last_err:
                    last_err = d
                    last_err_good = last_good
                elif last_err_good == last_good:
                    skip = True

            else:
                last_err = None
                last_good = d

            series_data.append((s, d, state, skip, last_good))
            self.handleData(s, d, state, skip, last_good)

        with self.lock:
            self.all_data.extend(series_data)

        if self.config.has_option('main', 'graph_dir'):
            self.outputGraphs(s, series_data)

    def run(self):
        series = self.source.getTestSeries(self.options.branches, self.options.start_time, self.options.tests)
        self.done = False
        def runner():
            while not self.done:
                try:
                    with self.lock:
                        if not series:
                            break
                        s = series.pop()
                    self.handleSeries(s)
                except KeyboardInterrupt:
                    print "Exiting..."
                    self.done = True
                    break

        threads = []
        for i in range(4):
            t = threading.Thread(target=runner)
            t.start()
            threads.append(t)

        while not self.done:
            try:
                alldone = True
                for t in threads:
                    if t.isAlive():
                        alldone = False
                        break
                if alldone:
                    self.done = True
                else:
                    time.sleep(1)
            except KeyboardInterrupt:
                print "Exiting..."
                self.done = True
                    
        for t in threads:
            t.join()

        if self.config.has_option('main', 'json'):
            self.outputJson()

        if self.config.has_option('main', 'dashboard_dir'):
            self.outputDashboard()

        if not self.options.catchup:
            self.findInactiveMachines()

if __name__ == "__main__":
    import sys
    from datetime import datetime
    from optparse import OptionParser
    from ConfigParser import SafeConfigParser

    parser = OptionParser()
    parser.add_option("-b", "--branch", dest="branches", action="append")
    parser.add_option("-t", "--test", dest="tests", action="append")
    parser.add_option("-o", "--output", dest="output", help="output file")
    parser.add_option("-q", "--quiet", dest="verbosity", action="store_const", const=log.WARN)
    parser.add_option("-v", "--verbose", dest="verbosity", action="store_const", const=log.DEBUG)
    parser.add_option("-e", "--email", dest="addresses", help="send regression notices to this email address", action="append")
    parser.add_option("-m", "--machine-email", dest="machine_addresses", help="send machine notices to this email address", action="append")
    parser.add_option("-c", "--config", dest="config", help="config file to read")
    parser.add_option("", "--start-time", dest="start_time", type="int", help="timestamp for when we start looking at data")
    parser.add_option("", "--catchup", dest="catchup", action="store_true", help="Don't output any warnings, just process data")

    parser.set_defaults(
            branches = [],
            tests = [],
            start_time = time.time() - 30*24*3600,
            verbosity = log.INFO,
            output = None,
            json = None,
            addresses = [],
            machine_addresses = [],
            config = "analysis.cfg",
            catchup = False,
            )

    options, args = parser.parse_args()

    config = SafeConfigParser()
    config.add_section('main')
    config.set('main', 'warning_history', 'warning_history.json')
    config.set('main', 'pushdates', 'pushdates.json')
    config.read([options.config])

    if options.addresses:
        config.set('main', 'regression_emails', ",".join(option.addresses))
    if options.machine_addresses:
        config.set('main', 'machine_emails', ",".join(option.machine_addresses))

    runner = AnalysisRunner(options, config)
    try:
        runner.run()
    finally:
        try:
            runner.saveWarningHistory()
        finally:
            runner.savePushDates()