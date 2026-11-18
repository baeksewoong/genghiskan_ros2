"""CLI helper to send an unload2 SQS command and optionally wait for robot-events."""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import uuid

import boto3

from sfarm_bridge.sfarm_bridge import (
    DEFAULT_COMMAND_QUEUE_URL,
    DEFAULT_EVENT_QUEUE_URL,
    load_dotenv,
)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse CLI arguments for SQS unload2 test."""
    parser = argparse.ArgumentParser(
        description='Send an unload2 SQS command and verify the robot-events response.'
    )
    parser.add_argument(
        '--work-id', type=int, default=9001, help='work_id to send (default: 9001)'
    )
    parser.add_argument(
        '--receive-pos-id',
        type=int,
        default=1,
        help='int8 receive_pos_id to send (default: 1, range: -128..127)',
    )
    parser.add_argument(
        '--typo-key',
        action='store_true',
        help='Send recieve_pos_id instead of receive_pos_id to test fallback parsing',
    )
    parser.add_argument(
        '--send-only',
        action='store_true',
        help='Only send to robot-commands.fifo without polling robot-events',
    )
    parser.add_argument(
        '--timeout',
        type=float,
        default=25.0,
        help='Seconds to wait for matching event in robot-events (default: 25.0)',
    )
    parser.add_argument(
        '--keep-event',
        action='store_true',
        help='Do not delete the matched test event from robot-events',
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Send an unload2 test command to SQS and inspect robot-events."""
    args = parse_args(argv)
    if not (-128 <= args.receive_pos_id <= 127):
        print(
            f'Error: receive_pos_id={args.receive_pos_id} out of int8 range (-128..127)',
            file=sys.stderr,
        )
        return 2

    load_dotenv()
    region = os.getenv('AWS_REGION') or os.getenv('AWS_DEFAULT_REGION') or 'ap-northeast-2'
    cmd_url = os.getenv('COMMAND_QUEUE_URL', DEFAULT_COMMAND_QUEUE_URL)
    evt_url = os.getenv('EVENT_QUEUE_URL', DEFAULT_EVENT_QUEUE_URL)

    pos_key = 'recieve_pos_id' if args.typo_key else 'receive_pos_id'
    payload = {
        'type': 'unload2',
        'work_id': args.work_id,
        pos_key: args.receive_pos_id,
    }

    sqs = boto3.client('sqs', region_name=region)
    send_params = {
        'QueueUrl': cmd_url,
        'MessageBody': json.dumps(payload, ensure_ascii=False),
    }
    if cmd_url.endswith('.fifo'):
        send_params['MessageGroupId'] = 'unload2-test'
        send_params['MessageDeduplicationId'] = f'unload2-test-{uuid.uuid4()}'

    resp = sqs.send_message(**send_params)
    print(f'[SENT] queue={cmd_url}')
    print(f'       message_id={resp["MessageId"]} body={send_params["MessageBody"]}')

    if args.send_only:
        return 0

    deadline = time.monotonic() + args.timeout
    print(f'[WAIT] polling {evt_url} for work_id={args.work_id} ...')
    while time.monotonic() < deadline:
        wait_sec = max(1, min(10, int(deadline - time.monotonic())))
        recv = sqs.receive_message(
            QueueUrl=evt_url,
            MaxNumberOfMessages=10,
            WaitTimeSeconds=wait_sec,
        )
        for msg in recv.get('Messages', []):
            try:
                body = json.loads(msg['Body'])
            except json.JSONDecodeError:
                continue
            if (
                body.get('work_id') == args.work_id
                and body.get('type') in ('success_unload2', 'fail_unload2')
            ):
                print(f'[EVENT] message_id={msg["MessageId"]} body={json.dumps(body)}')
                if not args.keep_event:
                    sqs.delete_message(
                        QueueUrl=evt_url,
                        ReceiptHandle=msg['ReceiptHandle'],
                    )
                    print('[DELETED] matched test event deleted from robot-events')
                return 0

    print(
        f'[TIMEOUT] no unload2 event for work_id={args.work_id} within {args.timeout}s',
        file=sys.stderr,
    )
    return 1


if __name__ == '__main__':
    raise SystemExit(main())
