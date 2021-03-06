"""
XDF based protocols
-------------------

This kind of file format is our preferred file format. It is `open-source, well-defined and extensible <https://github.com/sccn/xdf/wiki/Specifications>`_ and has `pxdf <https://pypi.org/project/pyxdf/>`_ to load it with Python. You will need one file.

- :code:`.xdf`

Data
****

Because LabRecorder can record multiple streams into a single :code:`.xdf`-file. These files can contain therefore not only EEG and EMG, but also e.g. pupilometric data, respiration effort, grip force, and many more. As it allows to record multiple streams, it also offers the option to record coordinates (as e.g. sent with every pulse from localite version 4.0) together with the raw data (as sent e.g. by eego or bvr) and additional markers. 

Coordinates
***********

In the optimal case, the :code:`.xdf`-file contains already sufficient information about the coordinates, and pairing is automatic. Yet, there will be some :code:`.xdf`-files, where not all streams were recorded. This might have happened e.g. due to errors in the recording script, an erroneous automated recording, or during manual recording with LabRecorder. In these cases, information about coordinates or other markers can be missing. The pairing of coordinates with a specific trace needs to be reconstructed manually (see :ref:`support-link-coords`).
 
If multiple protocols were recorded in one :code:`xdf`-file, as often happened during manual recording, we will have hundreds of stimuli. Worse, it can be that even marker-streams are missing, and there is no information when a protocol started within the long recording. Linking them to the correct coordinates is tricky, and the best chance is probably taking account of the relative latency between subsequent stimuli.

"""
from offspect.types import Annotations, FileName
from offspect import release
from offspect.cache.check import VALID_READOUTS, SPECIFIC_TRACEKEYS
from typing import List, Union, Any, Dict
from liesl.api import XDFFile
from liesl.files.xdf.load import XDFStream
from offspect.input.tms.matprotconv import get_coords_from_xml
from offspect.types import FileName, Coordinate, MetaData, Annotations, TraceData
from pathlib import Path
from math import nan, inf
import time
import json
import numpy as np


def decode(mark: str) -> Any:
    try:
        msg = json.loads(mark[0])
        return msg
    except json.JSONDecodeError:
        return mark[0]


def yield_events(stream, select_event="coil_0_didt"):
    """go through all triggers in the stream, and  yield the coordinates

    x,y,z can be [None, None, None] if the coil was out of sight of the NDI camera!

    Otherwise, yields a list of floats
    """
    marker = iter(stream.time_series)
    tstamps = iter(stream.time_stamps)
    skip = False
    didt = None
    tout_ts = None
    try:
        while True:
            msg = decode(next(marker))
            ts = next(tstamps)
            if msg == "Starte Hotspotsuche" or msg == "Starte Ruhemotorschwelle":
                # print(msg)
                skip = True
            if msg == "Starte freien Modus":
                # print(msg)
                skip = False
            if skip:
                continue
            if type(msg) is dict:
                if select_event in msg.keys():
                    didt = msg[select_event]
                    tout_ts = ts  # this is when we received a TriggerOut from Localite
                    # the didt is always send prior to the actual response
                if "amplitude" in msg.keys() and msg["amplitude"] != 0:
                    pos = [msg[dim] for dim in ["x", "y", "z"]]
                    # positions are none if the coil was not int the scope of
                    # the NDI cameras
                    tout_ts = (
                        tout_ts or ts
                    )  # pick the ts of the msg, if there was no coil_X_didt
                    mso = msg["amplitude"]
                    if not any(p == None for p in pos):
                        yield tout_ts, pos, mso, didt
                        tout_ts = None

    except StopIteration:
        return


def pick_stream_with_channel(channel: str, streams: Dict[str, XDFStream]) -> XDFStream:
    chans: List[str] = []
    for stream in streams.values():
        if stream.channel_labels is not None:
            chans.extend(stream.channel_labels)
            if channel in stream.channel_labels:
                datastream = stream

    if datastream is None:
        raise IndexError(
            f"Could not find the channel in any stream in the file. Available are: {chans}"
        )
    return datastream


def find_closest_samples(stream: XDFStream, tstamps: List[float]) -> List[int]:
    event_samples = []
    for ts in tstamps:
        idx = int(np.argmin(np.abs(stream.time_stamps - ts)))
        event_samples.append(idx)
    return event_samples


# -----------------------------------------------------------------------------


def prepare_annotations(
    xdffile: FileName,
    channel: str,
    readout: str,
    pre_in_ms: float,
    post_in_ms: float,
    xmlfile: FileName = None,
) -> Annotations:
    """load a documentation.txt and cnt-files and distill annotations from them
    
    args
    ----
    xmlfile: FileName
        an option xml file with information about the target coordinates 

    readout: str
        which readout to use (see :data:`~.VALID_READOUTS`)
    channel: str
        which channel to pick
    pre_in_ms: float
        how many ms to cut before the tms
    post_in_ms: float
        how many ms to cut after the tms
    xdffile: FileName
        the :code:`.xdf`-file with the recorded streams, e.g. data and markers
    returns
    -------
    annotation: Annotations
        the annotations for this origin files
    """

    # ------------------
    event_names = "coil_0_didt"  # TODO make it a function argument eventually
    streams = XDFFile(xdffile)
    try:
        stream = streams["localite_marker"]
        # initialize only when localite marker was found!
        coords = []
        trigout_times = []
        stimulation_intensity_mso = []
        stimulation_intensity_didt = []

        for ts, xyz, mso, didt in yield_events(stream, event_names):
            trigout_times.append(ts)
            coords.append(xyz)
            stimulation_intensity_mso.append(mso)
            stimulation_intensity_didt.append(didt)

    except KeyError:
        if xmlfile is not None:
            coords = get_coords_from_xml(xmlfile)
            print(f"XDF: Fall back to coordinates from {xmlfile}")
        else:
            print(f"XDF: No coordinates available, Filling in [nan, nan, nan]")

            def yield_nan():
                while True:
                    yield [nan, nan, nan]

            coords = yield_nan()
        stimulation_intensity_mso = [nan for i in range(len(coords))]
        stimulation_intensity_didt = [nan for i in range(len(coords))]

    datastream = pick_stream_with_channel(channel, streams)
    cix = datastream.channel_labels.index(channel)
    event_samples = find_closest_samples(datastream, trigout_times)
    event_times = [
        float(t)
        for t in datastream.time_stamps[event_samples] - datastream.time_stamps[0]
    ]

    # global fields
    origin = Path(xdffile).name
    fs = datastream.nominal_srate
    filedate = time.ctime(Path(xdffile).stat().st_mtime)
    subject = ""  # TODO parse from correctly organized file
    channel_labels = [channel]
    samples_pre_event = int(pre_in_ms * fs / 1000)
    samples_post_event = int(post_in_ms * fs / 1000)
    # trace fields
    time_since_last_pulse = [inf] + [
        a - b for a, b in zip(event_times[1:], event_times[0:-1])
    ]

    traceattrs: List[MetaData] = []
    for idx, t in enumerate(event_samples):
        tattr = {
            "id": idx,
            "event_name": event_names,
            "event_sample": event_samples[idx],
            "event_time": event_times[idx],
            "xyz_coords": coords[idx],
            "time_since_last_pulse_in_s": time_since_last_pulse[idx],
            "stimulation_intensity_mso": stimulation_intensity_mso[idx],
            "stimulation_intensity_didt": stimulation_intensity_didt[idx],
            "reject": False,
            "comment": "",
            "examiner": "",
            "onset_shift": 0,
        }
        for key in SPECIFIC_TRACEKEYS[readout].keys():
            if key not in tattr.keys():
                tattr[key] = nan
        traceattrs.append(tattr)

    anno: Annotations = {
        "origin": origin,
        "attrs": {
            "filedate": filedate,
            "subject": subject,
            "samplingrate": fs,
            "samples_pre_event": samples_pre_event,
            "samples_post_event": samples_post_event,
            "channel_labels": channel_labels,
            "readout": readout,
            "global_comment": "",
            "history": "",
            "version": release,
        },
        "traces": traceattrs,
    }
    return anno


def cut_traces(xdffile: FileName, annotation: Annotations) -> List[TraceData]:
    """cut the tracedate from a matfile given Annotations
    args
    ----
    xdfile: FileName
        the xdffile for cutting the data. must correspond in name to the one specified in the annotation
    annotation: Annotations
        the annotations specifying e.g. onsets as well as pre and post durations

    returns
    -------
    traces: List[TraceData]
    """

    streams = XDFFile(xdffile)
    channel = annotation["attrs"]["channel_labels"][0]
    print("Selecting traces for channel", channel)
    datastream = pick_stream_with_channel(channel, streams)
    cix = datastream.channel_labels.index(channel)

    pre = annotation["attrs"]["samples_pre_event"]
    post = annotation["attrs"]["samples_post_event"]
    traces = []
    for attrs in annotation["traces"]:
        onset = attrs["event_sample"]
        trace = datastream.time_series[onset - pre : onset + post, cix]
        traces.append(trace)
    return traces


if __name__ == "__main__":
    xdffile = "/media/rgugg/server/mnt/data/data08/RawData/2019_ST_IN-TENS/EiHe/pre1/mapping_contra_R001.xdf"
    pre_in_ms = 100
    post_in_ms = 100
    readout = "contralateral_mep"
    channel = "EDC_L"
    anno = prepare_annotations(xdffile, channel, readout, pre_in_ms, post_in_ms)
    for k, v in anno.items():
        if type(v) is list:
            print("Trial Count: ", len(v))
        elif type(v) is dict:
            for _k, _v in v.items():
                print(_k, ":", _v)
        else:
            print(k, ":", v)

