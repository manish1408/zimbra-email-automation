from app.services.zimbra.mail_client import ZimbraFolder, ZimbraMailClient


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
