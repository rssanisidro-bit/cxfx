package org.tju.challenge.lancodeshare;

import android.app.Activity;
import android.content.ClipData;
import android.content.ContentResolver;
import android.content.Intent;
import android.database.Cursor;
import android.net.Uri;
import android.provider.OpenableColumns;

import java.io.ByteArrayOutputStream;
import java.io.InputStream;
import java.nio.charset.Charset;

public final class NativeTextBridge {
    private NativeTextBridge() {
    }

    public static Intent createOpenDocumentIntent() {
        Intent intent = new Intent(Intent.ACTION_OPEN_DOCUMENT);
        intent.addCategory(Intent.CATEGORY_OPENABLE);
        intent.setType("*/*");
        intent.putExtra(Intent.EXTRA_ALLOW_MULTIPLE, false);
        intent.putExtra(Intent.EXTRA_MIME_TYPES, new String[] {
                "text/*",
                "application/json",
                "application/xml",
                "application/javascript",
                "application/x-python-code",
                "application/octet-stream"
        });
        intent.addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION);
        intent.addFlags(Intent.FLAG_GRANT_PERSISTABLE_URI_PERMISSION);
        return intent;
    }

    public static String extractResultUri(Intent data) {
        Uri uri = data == null ? null : data.getData();
        if (uri == null && data != null) {
            ClipData clipData = data.getClipData();
            if (clipData != null && clipData.getItemCount() > 0 && clipData.getItemAt(0) != null) {
                uri = clipData.getItemAt(0).getUri();
            }
        }
        if (uri == null) {
            throw new IllegalArgumentException("Android did not return a readable file URI");
        }
        return uri.toString();
    }

    public static String getDisplayNameForUri(Activity activity, String uriText) {
        Uri uri = Uri.parse(uriText);
        ContentResolver resolver = activity.getContentResolver();
        String name = null;
        try (Cursor cursor = resolver.query(uri, null, null, null, null)) {
            if (cursor != null) {
                int index = cursor.getColumnIndex(OpenableColumns.DISPLAY_NAME);
                if (index >= 0 && cursor.moveToFirst()) {
                    name = cursor.getString(index);
                }
            }
        } catch (Exception ignored) {
        }
        if (name == null || name.trim().isEmpty()) {
            name = "code.py";
        }
        return name;
    }

    public static String readUriAsText(Activity activity, String uriText, String charsetName, int maxBytes) throws Exception {
        Uri uri = Uri.parse(uriText);
        ContentResolver resolver = activity.getContentResolver();
        try {
            resolver.takePersistableUriPermission(uri, Intent.FLAG_GRANT_READ_URI_PERMISSION);
        } catch (Exception ignored) {
        }

        ByteArrayOutputStream output = new ByteArrayOutputStream();
        byte[] buffer = new byte[64 * 1024];
        int total = 0;
        try (InputStream input = resolver.openInputStream(uri)) {
            if (input == null) {
                throw new IllegalStateException("Could not open the selected file");
            }
            int read;
            while ((read = input.read(buffer)) != -1) {
                total += read;
                if (total > maxBytes) {
                    throw new IllegalStateException("Selected file is larger than the allowed limit");
                }
                output.write(buffer, 0, read);
            }
        }
        return new String(output.toByteArray(), Charset.forName(charsetName));
    }
}
