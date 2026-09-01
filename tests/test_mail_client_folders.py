from app.services.zimbra.mail_client import (
    ZimbraFolder,
    ZimbraMailClient,
    parse_zimbra_message_id,
    zimbra_message_id_variants,
)


def test_folder_matches_by_name():
    folder = ZimbraFolder(id="100", name="Undelivered", path="/Undelivered")
    assert ZimbraMailClient.folder_matches(folder, "undelivered")


def test_folder_matches_by_path():
    folder = ZimbraFolder(id="101", name="Notifications", path="/INBOX/Platform Notifications")
    assert ZimbraMailClient.folder_matches(folder, "Platform Notifications")


def test_find_folder_id():
    folders = [
        ZimbraFolder(id="1", name="Inbox", path="/Inbox"),
        ZimbraFolder(id="2", name="Undelivered", path="/Undelivered"),
    ]
    client = ZimbraMailClient.__new__(ZimbraMailClient)
    assert client.find_folder_id(folders, "Undelivered") == "2"
    assert client.find_folder_id(folders, "Missing") is None


def test_parse_zimbra_message_id():
    assert parse_zimbra_message_id("203684") == "203684"
    assert parse_zimbra_message_id("-203684") == "-203684"
    assert parse_zimbra_message_id(" 203684 ") == "203684"
    assert parse_zimbra_message_id("subject:invoice") is None
    assert parse_zimbra_message_id("abc123") is None


def test_zimbra_message_id_variants():
    assert zimbra_message_id_variants("203684") == ["203684", "-203684"]
    assert zimbra_message_id_variants("-203684") == ["-203684", "203684"]
    assert zimbra_message_id_variants("msg-42") == ["msg-42"]
