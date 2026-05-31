"""
build_slides.py  —  Meadows v. Washington University: Employment Timeline
Builds a hybrid Google Slides deck from recorded video segments + phase screenshots.

Requires:
  - credentials.json  (OAuth 2.0 Desktop client, from Google Cloud Console)
  - recording_output/manifest.json  (produced by record_segments.js)

Run once: python build_slides.py  →  opens browser for OAuth, then builds the deck.
"""

import os, json, time, sys
from pathlib import Path

from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

SCOPES = [
    'https://www.googleapis.com/auth/presentations',
    'https://www.googleapis.com/auth/drive.file',
]

HERE            = Path(__file__).parent
CREDENTIALS     = HERE / 'credentials.json'
TOKEN           = HERE / 'token.json'
MANIFEST        = HERE / 'recording_output' / 'manifest.json'
PRES_TITLE      = 'Meadows v. Washington University — Employment Timeline'

# Google Slides canvas in EMU (1 inch = 914400 EMU)
SLIDE_W = 9144000   # 10 inches
SLIDE_H = 5143500   # 5.625 inches  (16:9)

# Slide definition — each entry maps to one slide
#   type: 'video' | 'image' | 'title'
#   asset_id: key into manifest videos/screenshots lists
SLIDE_PLAN = [
    { 'type': 'title', 'title': 'Meadows v. Washington University',
      'subtitle': 'Employment Timeline — Orthopedics Department, 1977–2024' },

    { 'type': 'video',  'asset_id': 'seg1_initial_growth',
      'label': 'Bars growing: 1977 → 2018' },

    { 'type': 'image',  'asset_id': 'phase1_ellner_director',
      'label': '2018: Jenifer Ellner Becomes Revenue Cycle Director' },

    { 'type': 'video',  'asset_id': 'seg2_2018_to_2019',
      'label': 'Timeline advancing: 2018 → 2019' },

    { 'type': 'image',  'asset_id': 'phase2_daniel_fired',
      'label': '2019: Ellner Terminates Doritha Daniel' },

    { 'type': 'video',  'asset_id': 'seg3_2019_to_2021',
      'label': 'Timeline advancing: 2019 → 2021' },

    { 'type': 'image',  'asset_id': 'phase3_dayton_joins',
      'label': '2021: Cody Dayton Joins Orthopedics' },

    { 'type': 'video',  'asset_id': 'seg4_2021_to_2022',
      'label': 'Timeline advancing: 2021 → 2022' },

    { 'type': 'image',  'asset_id': 'phase4_hanewinkel_joins',
      'label': '2022: Kimberlee Hanewinkel Joins Orthopedics' },

    { 'type': 'video',  'asset_id': 'seg5_2022_to_firing',
      'label': 'Timeline advancing: 2022 → June 2022 (firing sequence)' },

    { 'type': 'image',  'asset_id': 'phase5_five_depart',
      'label': 'June–July 2022: Five Long-Tenure Employees Depart' },

    { 'type': 'image',  'asset_id': 'phase6_meadows_terminated',
      'label': 'June 17, 2022: Washington University Terminates Vanessa Meadows' },

    { 'type': 'video',  'asset_id': 'seg6_kortnie_arrival',
      'label': 'November 2022: Kortnie Sronce Arrives' },

    { 'type': 'image',  'asset_id': 'phase7_sronce_joins',
      'label': 'November 2022: Kortnie Sronce Joins — Five Months After Meadows' },
]


# ── Auth ─────────────────────────────────────────────────────────────────────

def get_credentials():
    creds = None
    if TOKEN.exists():
        creds = Credentials.from_authorized_user_file(str(TOKEN), SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not CREDENTIALS.exists():
                sys.exit(
                    '\nERROR: credentials.json not found.\n'
                    'Download it from Google Cloud Console → APIs & Services → Credentials\n'
                    f'and save it to:  {CREDENTIALS}\n'
                )
            flow = InstalledAppFlow.from_client_secrets_file(str(CREDENTIALS), SCOPES)
            creds = flow.run_local_server(port=0)
        TOKEN.write_text(creds.to_json())
    return creds


# ── Drive helpers ─────────────────────────────────────────────────────────────

def create_drive_folder(drive, name):
    meta = {'name': name, 'mimeType': 'application/vnd.google-apps.folder'}
    f = drive.files().create(body=meta, fields='id').execute()
    return f['id']

def upload_file(drive, local_path, name, mime_type, folder_id):
    print(f'  Uploading {name} …', end=' ', flush=True)
    body = {'name': name, 'parents': [folder_id]}
    media = MediaFileUpload(str(local_path), mimetype=mime_type, resumable=True)
    f = drive.files().create(body=body, media_body=media, fields='id').execute()
    print('done')
    return f['id']

def make_public(drive, file_id):
    drive.permissions().create(
        fileId=file_id,
        body={'type': 'anyone', 'role': 'reader'},
        fields='id'
    ).execute()
    return f'https://drive.google.com/uc?id={file_id}'

def wait_for_video_processing(drive, file_id, max_wait=120):
    """Poll until Drive has finished processing the video."""
    print(f'    Waiting for video processing …', end='', flush=True)
    for _ in range(max_wait // 5):
        meta = drive.files().get(fileId=file_id, fields='videoMediaMetadata,processingState').execute()
        state = meta.get('processingState', 'unknown')
        if state in ('succeeded', 'unknown') or 'videoMediaMetadata' in meta:
            print(' ready')
            return
        print('.', end='', flush=True)
        time.sleep(5)
    print(' (timed out — proceeding anyway)')


# ── Slides helpers ────────────────────────────────────────────────────────────

def emu(n): return {'magnitude': n, 'unit': 'EMU'}

def full_bleed_props(slide_id):
    return {
        'pageObjectId': slide_id,
        'size': {'width': emu(SLIDE_W), 'height': emu(SLIDE_H)},
        'transform': {'scaleX': 1, 'scaleY': 1, 'translateX': 0, 'translateY': 0, 'unit': 'EMU'},
    }

def batch(slides, pres_id, requests):
    return slides.presentations().batchUpdate(
        presentationId=pres_id, body={'requests': requests}
    ).execute()


def add_title_slide(slides, pres_id, slide_id, title, subtitle):
    requests = [
        {'updateSlideProperties': {
            'objectId': slide_id,
            'slideProperties': {'masterObjectId': None},
            'fields': 'slideBackgroundFill',
        }},
        {'updatePageProperties': {
            'objectId': slide_id,
            'pageProperties': {
                'pageBackgroundFill': {
                    'solidFill': {'color': {'rgbColor': {'red': 0.09, 'green': 0.11, 'blue': 0.18}}}
                }
            },
            'fields': 'pageBackgroundFill',
        }},
    ]
    # Title text box
    title_id = f'{slide_id}_title'
    requests += [
        {'createShape': {
            'objectId': title_id,
            'shapeType': 'TEXT_BOX',
            'elementProperties': {
                'pageObjectId': slide_id,
                'size': {'width': emu(7600000), 'height': emu(1200000)},
                'transform': {'scaleX': 1, 'scaleY': 1, 'translateX': emu(772000)['magnitude'], 'translateY': emu(1600000)['magnitude'], 'unit': 'EMU'},
            },
        }},
        {'insertText': {'objectId': title_id, 'text': title}},
        {'updateTextStyle': {
            'objectId': title_id,
            'style': {
                'foregroundColor': {'opaqueColor': {'rgbColor': {'red': 1.0, 'green': 1.0, 'blue': 1.0}}},
                'fontSize': {'magnitude': 40, 'unit': 'PT'},
                'bold': True,
                'fontFamily': 'Inter',
            },
            'fields': 'foregroundColor,fontSize,bold,fontFamily',
        }},
    ]
    # Subtitle text box
    sub_id = f'{slide_id}_sub'
    requests += [
        {'createShape': {
            'objectId': sub_id,
            'shapeType': 'TEXT_BOX',
            'elementProperties': {
                'pageObjectId': slide_id,
                'size': {'width': emu(7600000), 'height': emu(700000)},
                'transform': {'scaleX': 1, 'scaleY': 1, 'translateX': emu(772000)['magnitude'], 'translateY': emu(2900000)['magnitude'], 'unit': 'EMU'},
            },
        }},
        {'insertText': {'objectId': sub_id, 'text': subtitle}},
        {'updateTextStyle': {
            'objectId': sub_id,
            'style': {
                'foregroundColor': {'opaqueColor': {'rgbColor': {'red': 0.65, 'green': 0.73, 'blue': 0.85}}},
                'fontSize': {'magnitude': 22, 'unit': 'PT'},
                'fontFamily': 'Inter',
            },
            'fields': 'foregroundColor,fontSize,fontFamily',
        }},
    ]
    batch(slides, pres_id, requests)


def add_video_slide(slides, pres_id, slide_id, drive_file_id, label):
    vid_id = f'{slide_id}_video'
    requests = [
        # Dark background
        {'updatePageProperties': {
            'objectId': slide_id,
            'pageProperties': {
                'pageBackgroundFill': {
                    'solidFill': {'color': {'rgbColor': {'red': 0.05, 'green': 0.06, 'blue': 0.09}}}
                }
            },
            'fields': 'pageBackgroundFill',
        }},
        # Full-bleed video
        {'createVideo': {
            'objectId': vid_id,
            'elementProperties': full_bleed_props(slide_id),
            'source': 'DRIVE',
            'id': drive_file_id,
        }},
        # Auto-play on presentation
        {'updateVideoProperties': {
            'objectId': vid_id,
            'videoProperties': {'autoPlay': True, 'mute': True},
            'fields': 'autoPlay,mute',
        }},
    ]
    batch(slides, pres_id, requests)


def add_image_slide(slides, pres_id, slide_id, public_url):
    img_id = f'{slide_id}_img'
    requests = [
        {'updatePageProperties': {
            'objectId': slide_id,
            'pageProperties': {
                'pageBackgroundFill': {
                    'solidFill': {'color': {'rgbColor': {'red': 0.05, 'green': 0.06, 'blue': 0.09}}}
                }
            },
            'fields': 'pageBackgroundFill',
        }},
        {'createImage': {
            'objectId': img_id,
            'url': public_url,
            'elementProperties': full_bleed_props(slide_id),
        }},
    ]
    batch(slides, pres_id, requests)


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    if not MANIFEST.exists():
        sys.exit(f'\nERROR: manifest.json not found at {MANIFEST}\nRun:  node record_segments.js  first.\n')

    manifest = json.loads(MANIFEST.read_text())
    # Index assets by id
    assets = {}
    for v in manifest['videos']:
        assets[v['id']] = {'path': v['path'], 'type': 'video'}
    for s in manifest['screenshots']:
        assets[s['id']] = {'path': s['path'], 'type': 'image'}

    print('Authenticating with Google …')
    creds  = get_credentials()
    slides = build('slides', 'v1', credentials=creds)
    drive  = build('drive',  'v3', credentials=creds)

    # Create Drive folder for assets
    print('\nCreating Drive folder …')
    folder_id = create_drive_folder(drive, 'Meadows Timeline Assets')

    # Upload all assets; for images make them public; for videos wait for processing
    print('\nUploading assets to Drive …')
    drive_ids   = {}   # asset_id → drive_file_id
    public_urls = {}   # asset_id → public URL (images only)

    for asset_id, info in assets.items():
        p = Path(info['path'])
        if info['type'] == 'video':
            fid = upload_file(drive, p, p.name, 'video/mp4', folder_id)
            wait_for_video_processing(drive, fid)
            drive_ids[asset_id] = fid
        else:
            fid = upload_file(drive, p, p.name, 'image/png', folder_id)
            url = make_public(drive, fid)
            drive_ids[asset_id]   = fid
            public_urls[asset_id] = url

    # Create presentation
    print('\nCreating presentation …')
    pres = slides.presentations().create(
        body={'title': PRES_TITLE}
    ).execute()
    pres_id = pres['presentationId']
    default_slide_id = pres['slides'][0]['objectId']
    print(f'  Presentation ID: {pres_id}')

    # Build slides
    # We repurpose the first default slide, then add new ones
    slide_ids = [default_slide_id]

    n_extra = len(SLIDE_PLAN) - 1
    if n_extra > 0:
        add_requests = [
            {'createSlide': {
                'insertionIndex': i + 1,
                'slideLayoutReference': {'predefinedLayout': 'BLANK'},
            }}
            for i in range(n_extra)
        ]
        result = batch(slides, pres_id, add_requests)
        for r in result.get('replies', []):
            if 'createSlide' in r:
                slide_ids.append(r['createSlide']['objectId'])

    print(f'\nBuilding {len(SLIDE_PLAN)} slides …')
    for i, plan in enumerate(SLIDE_PLAN):
        sid = slide_ids[i]
        print(f'  Slide {i+1}: {plan["label"] if "label" in plan else plan["title"]}')

        if plan['type'] == 'title':
            add_title_slide(slides, pres_id, sid, plan['title'], plan['subtitle'])

        elif plan['type'] == 'video':
            fid = drive_ids[plan['asset_id']]
            add_video_slide(slides, pres_id, sid, fid, plan.get('label', ''))

        elif plan['type'] == 'image':
            url = public_urls[plan['asset_id']]
            add_image_slide(slides, pres_id, sid, url)

    url = f'https://docs.google.com/presentation/d/{pres_id}/edit'
    print(f'\n✓ Done.\n\nOpen your presentation:\n  {url}\n')


if __name__ == '__main__':
    main()
