#!/usr/bin/env python

# Copyright 2012 - 2017, New York University and the TUF contributors
# SPDX-License-Identifier: MIT OR Apache-2.0

"""
<Program Name>
  test_indefinite_freeze_attack.py

<Author>
  Konstantin Andrianov.

<Started>
  March 10, 2012.

  April 1, 2014.
    Refactored to use the 'unittest' module (test conditions in code, rather
    than verifying text output), use pre-generated repository files, and
    discontinue use of the old repository tools. -vladimir.v.diaz

  March 9, 2016.
    Additional test added relating to issue:
    https://github.com/theupdateframework/tuf/issues/322
    If a metadata file is not updated (no indication of a new version
    available), the expiration of the pre-existing, locally trusted metadata
    must still be detected. This additional test complains if such does not
    occur, and accompanies code in tuf.client.updater:refresh() to detect it.
    -sebastien.awwad

<Copyright>
  See LICENSE-MIT OR LICENSE for licensing information.

<Purpose>
  Simulate an indefinite freeze attack.  In an indefinite freeze attack,
  attacker is able to respond to client's requests with the same, outdated
  metadata without the client being aware.
"""

import datetime
import os
import time
import tempfile
import shutil
import json
import logging
import unittest
import sys
from urllib import request

if sys.version_info >= (3, 3):
  import unittest.mock as mock
else:
  import mock

import tuf.formats
import tuf.log
import tuf.client.updater as updater
import tuf.repository_tool as repo_tool
import tuf.unittest_toolbox as unittest_toolbox
import tuf.roledb
import tuf.keydb
import tuf.exceptions

from tests import utils

import securesystemslib

# The repository tool is imported and logs console messages by default.  Disable
# console log messages generated by this unit test.
repo_tool.disable_console_log_messages()

logger = logging.getLogger(__name__)


class TestIndefiniteFreezeAttack(unittest_toolbox.Modified_TestCase):

  @classmethod
  def setUpClass(cls):
    # Create a temporary directory to store the repository, metadata, and target
    # files.  'temporary_directory' must be deleted in TearDownModule() so that
    # temporary files are always removed, even when exceptions occur.
    cls.temporary_directory = tempfile.mkdtemp(dir=os.getcwd())

    # Launch a SimpleHTTPServer (serves files in the current directory).
    # Test cases will request metadata and target files that have been
    # pre-generated in 'tuf/tests/repository_data', which will be served by the
    # SimpleHTTPServer launched here.  The test cases of this unit test assume
    # the pre-generated metadata files have a specific structure, such
    # as a delegated role 'targets/role1', three target files, five key files,
    # etc.
    cls.server_process_handler = utils.TestServerProcess(log=logger)



  @classmethod
  def tearDownClass(cls):
    # Cleans the resources and flush the logged lines (if any).
    cls.server_process_handler.clean()

    # Remove the temporary repository directory, which should contain all the
    # metadata, targets, and key files generated of all the test cases.
    shutil.rmtree(cls.temporary_directory)




  def setUp(self):
    # We are inheriting from custom class.
    unittest_toolbox.Modified_TestCase.setUp(self)
    self.repository_name = 'test_repository1'

    # Copy the original repository files provided in the test folder so that
    # any modifications made to repository files are restricted to the copies.
    # The 'repository_data' directory is expected to exist in 'tuf/tests/'.
    original_repository_files = os.path.join(os.getcwd(), 'repository_data')
    temporary_repository_root = \
      self.make_temp_directory(directory=self.temporary_directory)

    # The original repository, keystore, and client directories will be copied
    # for each test case.
    original_repository = os.path.join(original_repository_files, 'repository')
    original_client = os.path.join(original_repository_files, 'client')
    original_keystore = os.path.join(original_repository_files, 'keystore')

    # Save references to the often-needed client repository directories.
    # Test cases need these references to access metadata and target files.
    self.repository_directory = \
      os.path.join(temporary_repository_root, 'repository')
    self.client_directory = os.path.join(temporary_repository_root, 'client')
    self.keystore_directory = os.path.join(temporary_repository_root, 'keystore')

    # Copy the original 'repository', 'client', and 'keystore' directories
    # to the temporary repository the test cases can use.
    shutil.copytree(original_repository, self.repository_directory)
    shutil.copytree(original_client, self.client_directory)
    shutil.copytree(original_keystore, self.keystore_directory)

    # Set the url prefix required by the 'tuf/client/updater.py' updater.
    # 'path/to/tmp/repository' -> 'localhost:8001/tmp/repository'.
    repository_basepath = self.repository_directory[len(os.getcwd()):]
    url_prefix = 'http://' + utils.TEST_HOST_ADDRESS + ':' \
        + str(self.server_process_handler.port) + repository_basepath

    # Setting 'tuf.settings.repository_directory' with the temporary client
    # directory copied from the original repository files.
    tuf.settings.repositories_directory = self.client_directory
    self.repository_mirrors = {'mirror1': {'url_prefix': url_prefix,
                                           'metadata_path': 'metadata',
                                           'targets_path': 'targets'}}

    # Create the repository instance.  The test cases will use this client
    # updater to refresh metadata, fetch target files, etc.
    self.repository_updater = updater.Updater(self.repository_name,
                                              self.repository_mirrors)


  def tearDown(self):
    tuf.roledb.clear_roledb(clear_all=True)
    tuf.keydb.clear_keydb(clear_all=True)

    # Logs stdout and stderr from the sever subprocess.
    self.server_process_handler.flush_log()

    # Remove temporary directory
    unittest_toolbox.Modified_TestCase.tearDown(self)


  def test_without_tuf(self):
    # Without TUF, Test 1 and Test 2 are functionally equivalent, so we skip
    # Test 1 and only perform Test 2.
    #
    # Test 1: If we find that the timestamp acquired from a mirror indicates
    #         that there is no new snapshot file, and our current snapshot
    #         file is expired, is it recognized as such?
    # Test 2: If an expired timestamp is downloaded, is it recognized as such?


    # Test 2 Begin:
    #
    # 'timestamp.json' specifies the latest version of the repository files.  A
    # client should only accept the same version of this file up to a certain
    # point, or else it cannot detect that new files are available for
    # download.  Modify the repository's timestamp.json' so that it expires
    # soon, copy it over to the client, and attempt to re-fetch the same
    # expired version.
    #
    # A non-TUF client (without a way to detect when metadata has expired) is
    # expected to download the same version, and thus the same outdated files.
    # Verify that the downloaded 'timestamp.json' contains the same file size
    # and hash as the one available locally.

    timestamp_path = os.path.join(self.repository_directory, 'metadata',
                                  'timestamp.json')

    timestamp_metadata = securesystemslib.util.load_json_file(timestamp_path)
    expiry_time = time.time() - 10
    expires = tuf.formats.unix_timestamp_to_datetime(int(expiry_time))
    expires = expires.isoformat() + 'Z'
    timestamp_metadata['signed']['expires'] = expires
    tuf.formats.check_signable_object_format(timestamp_metadata)

    with open(timestamp_path, 'wb') as file_object:
      # Explicitly specify the JSON separators for Python 2 + 3 consistency.
      timestamp_content = \
        json.dumps(timestamp_metadata, indent=1, separators=(',', ': '),
                   sort_keys=True).encode('utf-8')
      file_object.write(timestamp_content)

    client_timestamp_path = os.path.join(self.client_directory, 'timestamp.json')
    shutil.copy(timestamp_path, client_timestamp_path)

    length, hashes = securesystemslib.util.get_file_details(timestamp_path)
    fileinfo = tuf.formats.make_targets_fileinfo(length, hashes)

    url_prefix = self.repository_mirrors['mirror1']['url_prefix']
    url_file = os.path.join(url_prefix, 'metadata', 'timestamp.json')

    request.urlretrieve(url_file.replace('\\', '/'), client_timestamp_path)

    length, hashes = securesystemslib.util.get_file_details(client_timestamp_path)
    download_fileinfo = tuf.formats.make_targets_fileinfo(length, hashes)

    # Verify 'download_fileinfo' is equal to the current local file.
    self.assertEqual(download_fileinfo, fileinfo)


  def test_with_tuf(self):
    # Three tests are conducted here.
    #
    # Test 1: If we find that the timestamp acquired from a mirror indicates
    #         that there is no new snapshot file, and our current snapshot
    #         file is expired, is it recognized as such?
    # Test 2: If an expired timestamp is downloaded, is it recognized as such?
    # Test 3: If an expired Snapshot is downloaded, is it (1) rejected? (2) the
    # local Snapshot file deleted? (3) and is the client able to recover when
    # given a new, valid Snapshot?


    # Test 1 Begin:
    #
    # Addresses this issue: https://github.com/theupdateframework/tuf/issues/322
    #
    # If time has passed and our snapshot or targets role is expired, and
    # the mirror whose timestamp we fetched doesn't indicate the existence of a
    # new snapshot version, we still need to check that it's expired and notify
    # the software update system / application / user. This test creates that
    # scenario. The correct behavior is to raise an exception.
    #
    # Background: Expiration checks (updater._ensure_not_expired) were
    # previously conducted when the metadata file was downloaded. If no new
    # metadata file was downloaded, no expiry check would occur. In particular,
    # while root was checked for expiration at the beginning of each
    # updater.refresh() cycle, and timestamp was always checked because it was
    # always fetched, snapshot and targets were never checked if the user did
    # not receive evidence that they had changed. This bug allowed a class of
    # freeze attacks.
    # That bug was fixed and this test tests that fix going forward.

    # Modify the timestamp file on the remote repository.  'timestamp.json'
    # must be properly updated and signed with 'repository_tool.py', otherwise
    # the client will reject it as invalid metadata.

    # Load the repository
    repository = repo_tool.load_repository(self.repository_directory)

    # Load the snapshot and timestamp keys
    key_file = os.path.join(self.keystore_directory, 'timestamp_key')
    timestamp_private = repo_tool.import_ed25519_privatekey_from_file(key_file,
                                                                  'password')
    repository.timestamp.load_signing_key(timestamp_private)
    key_file = os.path.join(self.keystore_directory, 'snapshot_key')
    snapshot_private = repo_tool.import_ed25519_privatekey_from_file(key_file,
                                                                  'password')
    repository.snapshot.load_signing_key(snapshot_private)

    # sign snapshot with expiry in near future (earlier than e.g. timestamp)
    expiry = int(time.time() + 60*60)
    repository.snapshot.expiration = tuf.formats.unix_timestamp_to_datetime(
        expiry)
    repository.mark_dirty(['snapshot', 'timestamp'])
    repository.writeall()

    # And move the staged metadata to the "live" metadata.
    shutil.rmtree(os.path.join(self.repository_directory, 'metadata'))
    shutil.copytree(os.path.join(self.repository_directory, 'metadata.staged'),
                    os.path.join(self.repository_directory, 'metadata'))

    # Refresh metadata on the client. For this refresh, all data is not expired.
    logger.info('Test: Refreshing #1 - Initial metadata refresh occurring.')
    self.repository_updater.refresh()

    logger.info('Test: Refreshing #2 - refresh after local snapshot expiry.')

    # mock current time to one second after snapshot expiry
    mock_time = mock.Mock()
    mock_time.return_value = expiry + 1
    with mock.patch('time.time', mock_time):
      try:
        self.repository_updater.refresh() # We expect this to fail!

      except tuf.exceptions.ExpiredMetadataError:
        logger.info('Test: Refresh #2 - failed as expected. Expired local'
                    ' snapshot case generated a tuf.exceptions.ExpiredMetadataError'
                    ' exception as expected. Test pass.')

      else:
        self.fail('TUF failed to detect expired stale snapshot metadata. Freeze'
          ' attack successful.')




    # Test 2 Begin:
    #
    # 'timestamp.json' specifies the latest version of the repository files.
    # A client should only accept the same version of this file up to a certain
    # point, or else it cannot detect that new files are available for download.
    # Modify the repository's 'timestamp.json' so that it is about to expire,
    # copy it over the to client, wait a moment until it expires, and attempt to
    # re-fetch the same expired version.

    # The same scenario as in test_without_tuf() is followed here, except with
    # a TUF client. The TUF client performs a refresh of top-level metadata,
    # which includes 'timestamp.json', and should detect a freeze attack if
    # the repository serves an outdated 'timestamp.json'.

    # Modify the timestamp file on the remote repository.  'timestamp.json'
    # must be properly updated and signed with 'repository_tool.py', otherwise
    # the client will reject it as invalid metadata.  The resulting
    # 'timestamp.json' should be valid metadata, but expired (as intended).
    repository = repo_tool.load_repository(self.repository_directory)

    key_file = os.path.join(self.keystore_directory, 'timestamp_key')
    timestamp_private = repo_tool.import_ed25519_privatekey_from_file(key_file,
                                                                  'password')

    repository.timestamp.load_signing_key(timestamp_private)

    # Set timestamp metadata to expire soon.
    # We cannot set the timestamp expiration with
    # 'repository.timestamp.expiration = ...' with already-expired timestamp
    # metadata because of consistency checks that occur during that assignment.
    expiry_time = time.time() + 60*60
    datetime_object = tuf.formats.unix_timestamp_to_datetime(int(expiry_time))
    repository.timestamp.expiration = datetime_object
    repository.writeall()

    # Move the staged metadata to the "live" metadata.
    shutil.rmtree(os.path.join(self.repository_directory, 'metadata'))
    shutil.copytree(os.path.join(self.repository_directory, 'metadata.staged'),
                    os.path.join(self.repository_directory, 'metadata'))

    # mock current time to one second after timestamp expiry
    mock_time = mock.Mock()
    mock_time.return_value = expiry_time + 1
    with mock.patch('time.time', mock_time):
      try:
        self.repository_updater.refresh() # We expect NoWorkingMirrorError.

      except tuf.exceptions.NoWorkingMirrorError as e:
        # Make sure the contained error is ExpiredMetadataError
        for mirror_url, mirror_error in e.mirror_errors.items():
          self.assertTrue(isinstance(mirror_error, tuf.exceptions.ExpiredMetadataError))

      else:
        self.fail('TUF failed to detect expired, stale timestamp metadata.'
          ' Freeze attack successful.')




    # Test 3 Begin:
    #
    # Serve the client expired Snapshot.  The client should reject the given,
    # expired Snapshot and the locally trusted one, which should now be out of
    # date.
    # After the attack, attempt to re-issue a valid Snapshot to verify that
    # the client is still able to update. A bug previously caused snapshot
    # expiration or replay to result in an indefinite freeze; see
    # github.com/theupdateframework/tuf/issues/736
    repository = repo_tool.load_repository(self.repository_directory)

    ts_key_file = os.path.join(self.keystore_directory, 'timestamp_key')
    snapshot_key_file = os.path.join(self.keystore_directory, 'snapshot_key')
    timestamp_private = repo_tool.import_ed25519_privatekey_from_file(
        ts_key_file, 'password')
    snapshot_private = repo_tool.import_ed25519_privatekey_from_file(
        snapshot_key_file, 'password')

    repository.timestamp.load_signing_key(timestamp_private)
    repository.snapshot.load_signing_key(snapshot_private)

    # Set ts to expire in 1 month.
    ts_expiry_time = time.time() + 2630000

    # Set snapshot to expire in 1 hour.
    snapshot_expiry_time = time.time() + 60*60

    ts_datetime_object = tuf.formats.unix_timestamp_to_datetime(
        int(ts_expiry_time))
    snapshot_datetime_object = tuf.formats.unix_timestamp_to_datetime(
        int(snapshot_expiry_time))
    repository.timestamp.expiration = ts_datetime_object
    repository.snapshot.expiration = snapshot_datetime_object
    repository.writeall()

    # Move the staged metadata to the "live" metadata.
    shutil.rmtree(os.path.join(self.repository_directory, 'metadata'))
    shutil.copytree(os.path.join(self.repository_directory, 'metadata.staged'),
                    os.path.join(self.repository_directory, 'metadata'))

    # mock current time to one second after snapshot expiry
    mock_time = mock.Mock()
    mock_time.return_value = snapshot_expiry_time + 1
    with mock.patch('time.time', mock_time):
      try:
        # We expect the following refresh() to raise a NoWorkingMirrorError.
        self.repository_updater.refresh()

      except tuf.exceptions.NoWorkingMirrorError as e:
        # Make sure the contained error is ExpiredMetadataError
        for mirror_url, mirror_error in e.mirror_errors.items():
          self.assertTrue(isinstance(mirror_error, tuf.exceptions.ExpiredMetadataError))
          self.assertTrue(mirror_url.endswith('snapshot.json'))

      else:
        self.fail('TUF failed to detect expired, stale Snapshot metadata.'
          ' Freeze attack successful.')

    # The client should have rejected the malicious Snapshot metadata, and
    # distrusted the local snapshot file that is no longer valid.
    self.assertTrue('snapshot' not in self.repository_updater.metadata['current'])
    self.assertEqual(sorted(['root', 'targets', 'timestamp']),
        sorted(self.repository_updater.metadata['current']))

    # Verify that the client is able to recover from the malicious Snapshot.
    # Re-sign a valid Snapshot file that the client should accept.
    repository = repo_tool.load_repository(self.repository_directory)

    repository.timestamp.load_signing_key(timestamp_private)
    repository.snapshot.load_signing_key(snapshot_private)

    # Set snapshot to expire in 1 month.
    snapshot_expiry_time = time.time() + 2630000

    snapshot_datetime_object = tuf.formats.unix_timestamp_to_datetime(
        int(snapshot_expiry_time))
    repository.snapshot.expiration = snapshot_datetime_object
    repository.writeall()

    # Move the staged metadata to the "live" metadata.
    shutil.rmtree(os.path.join(self.repository_directory, 'metadata'))
    shutil.copytree(os.path.join(self.repository_directory, 'metadata.staged'),
                    os.path.join(self.repository_directory, 'metadata'))

    # Verify that the client accepts the valid metadata file.
    self.repository_updater.refresh()
    self.assertTrue('snapshot' in self.repository_updater.metadata['current'])
    self.assertEqual(sorted(['root', 'targets', 'timestamp', 'snapshot']),
        sorted(self.repository_updater.metadata['current']))



if __name__ == '__main__':
  utils.configure_test_logging(sys.argv)
  unittest.main()
