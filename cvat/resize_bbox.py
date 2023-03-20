""" Jupyter kernel doen't support multiprocessing... feeling saaaaaaaad """

# %% preparation
import os
import re
import tqdm
import glob
import zipfile
import datetime
import traceback
import multiprocessing

from cvat_sdk import make_client

import config as cfg

# %% constants
RESIZE_IDS = [40, 41, 42, 43, 48, 49, 60,
              62, 63, 64, 81, 82, 83, 84, 
              92, 93, 94, 99, 114, 118]
TIMEOUT = 120

TARGET_WIDTH = 50
TARGET_HEIGHT = 50

ANNOTATION_DIR = "/mnt/d/Documents/tmp"
TARGET_DIR = "/mnt/d/Documents/resize_anno"

# %% resize functions
def resize_zipfile(source_file, TARGET_WIDTH, TARGET_HEIGHT, TARGET_DIR):
    # resize lines in annotations.xml
    newlines = []
    with zipfile.ZipFile(source_file, 'r') as archive:
        annofile = archive.open('annotations.xml', 'r')
        lines = annofile.readlines()
        for line in lines:
            line = line.decode("utf-8")
            pattern_group = re.search('xtl="(\d+\.\d+)" ytl="(\d+\.\d+)" xbr="(\d+\.\d+)" ybr="(\d+\.\d+)"', line)
            if pattern_group is None:
                newlines.append(line)
                continue
            newline = resize_line(line, TARGET_WIDTH, TARGET_HEIGHT)
            newlines.append(newline)
    
    # write to target_path
    basename = f'{os.path.basename(source_file).split(".")[0]}-{TIMESTAMP}.xml'
    # basename = f'{os.path.basename(source_file).split(".")[0]}-{TIMESTAMP}.zip'
    
    target_zipfile = os.path.join(TARGET_DIR, basename)
    with open(target_zipfile, 'w') as f:
        f.write("".join(newlines))
    # with zipfile.ZipFile(target_zipfile, 'w') as archive:
    #     annofile = archive.writestr('annotations.xml', data="".join(newlines))
    return target_zipfile

def resize_line(line, TARGET_WIDTH, TARGET_HEIGHT):
    # extract xtl, ytl, xbr, ybr
    pattern_group = re.search('xtl="(\d+\.\d+)" ytl="(\d+\.\d+)" xbr="(\d+\.\d+)" ybr="(\d+\.\d+)"', line)
    xtl, ytl, xbr, ybr = pattern_group.groups()
    xtl = float(xtl)
    ytl = float(ytl)
    xbr = float(xbr)
    ybr = float(ybr)

    centre_point_x = (xtl + xbr) / 2
    centre_point_y = (ytl + ybr) / 2

    xtl = centre_point_x - TARGET_WIDTH / 2
    ytl = centre_point_y - TARGET_HEIGHT / 2
    xbr = centre_point_x + TARGET_WIDTH / 2
    ybr = centre_point_y + TARGET_HEIGHT / 2
    
    newline = line.replace(pattern_group.group(0), f'xtl="{xtl:.02f}" ytl="{ytl:.02f}" xbr="{xbr:.02f}" ybr="{ybr:.02f}"')

    return newline

def resize_upload_wrapper(host, port, username, password, import_format, task_id, import_file):
    with make_client(host=host, port=f"{port}", credentials=(f"{username}", f"{password}")) as client:
        client.tasks.retrieve(obj_id=task_id).import_annotations(
                format_name=import_format,
                filename=import_file,
                pbar=None,
                status_check_period=2,
                )

# %% main
if __name__ == "__main__":
    # generate timestamp string to avoid name conflict, or CVAT will alert "File with same name already exists"
    now = datetime.datetime.now()
    TIMESTAMP = now.strftime("%Y%m%d%H%M%S")

    if not os.path.exists(ANNOTATION_DIR):
        raise Exception("source path must exist")
    if not os.path.exists(TARGET_DIR):
        os.makedirs(TARGET_DIR)

    if os.path.samefile(ANNOTATION_DIR, TARGET_DIR):
        raise Exception("annotation_path and target_path must be different")
    
    if cfg.SSL:
        HOST = f"https://{cfg.SERVER}"
    else:
        HOST = f"http://{cfg.SERVER}"

    # %% resize and upload

    annolist = glob.glob(os.path.join(ANNOTATION_DIR, "*-*.zip"))
    finishlist = []
    failedlist = []
    for anno in tqdm.tqdm(annolist):
        filename = os.path.basename(anno)
        task_id = int(filename.split("-")[0])
        if task_id not in RESIZE_IDS:
            continue
        # request the task handler
        try:
            target_zipfile = resize_zipfile(anno, TARGET_WIDTH, TARGET_HEIGHT, TARGET_DIR)
            # iterate over all dumped annotations
            p = multiprocessing.Process(target=resize_upload_wrapper, args=(HOST, cfg.PORT, cfg.USERNAME, cfg.PASSWORD, cfg.IMPORT_FORMAT, task_id, target_zipfile,))
            p.start()
            p.join(timeout=TIMEOUT)
            if p.is_alive():
                print(f"Kill the import process of task {task_id}")
                failedlist.append(task_id)
                p.terminate()
            else:
                finishlist.append(task_id)
        except:
            print(f"Failed to update task {task_id}")
            print(traceback.format_exc())
            failedlist.append(task_id)

    notfoundlist = [x for x in RESIZE_IDS if x not in finishlist]
    print(f"Finished tasks: {finishlist}")
    print(f"Failed when processing: {failedlist}")
    print(f"Annotation files are not found for following tasks: {notfoundlist}")