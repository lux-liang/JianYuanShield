package com.vpsg.jianyuanshield.ui.components

import android.net.Uri
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.PickVisualMediaRequest
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.aspectRatio
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.rounded.AddPhotoAlternate
import androidx.compose.material.icons.rounded.Check
import androidx.compose.material.icons.rounded.PhotoCamera
import androidx.compose.material.icons.rounded.PhotoLibrary
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.ExposedDropdownMenuBox
import androidx.compose.material3.ExposedDropdownMenuDefaults
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.MenuAnchorType
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.OutlinedTextFieldDefaults
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import com.vpsg.jianyuanshield.core.CaptureUtils
import com.vpsg.jianyuanshield.domain.AttackOption
import com.vpsg.jianyuanshield.domain.ModelOption
import com.vpsg.jianyuanshield.ui.foundation.marchingAnts
import com.vpsg.jianyuanshield.ui.foundation.pressable
import com.vpsg.jianyuanshield.ui.theme.CardBg
import com.vpsg.jianyuanshield.ui.theme.Divider
import com.vpsg.jianyuanshield.ui.theme.GovBlue
import com.vpsg.jianyuanshield.ui.theme.GovBlueTint
import com.vpsg.jianyuanshield.ui.theme.Ink
import com.vpsg.jianyuanshield.ui.theme.InkSecondary
import com.vpsg.jianyuanshield.ui.theme.NeutralDot

/** Wrapping selector of watermark models — government selectable chips. */
@OptIn(ExperimentalLayoutApi::class)
@Composable
fun ModelSelector(
    models: List<ModelOption>,
    selectedId: String,
    onSelect: (ModelOption) -> Unit,
    modifier: Modifier = Modifier,
) {
    FlowRow(
        modifier = modifier.fillMaxWidth(),
        horizontalArrangement = Arrangement.spacedBy(10.dp),
        verticalArrangement = Arrangement.spacedBy(10.dp),
    ) {
        models.forEach { model ->
            val selected = model.id == selectedId
            // 统一蓝系:未选项用中性圆点,不再按模型上蓝/绿/琥珀/紫四色。
            val shape = RoundedCornerShape(12.dp)
            Row(
                modifier = Modifier
                    .height(44.dp)
                    .background(if (selected) GovBlueTint else CardBg, shape)
                    .border(1.5.dp, if (selected) GovBlue else Divider, shape)
                    .pressable(onClick = { onSelect(model) })
                    .padding(horizontal = 16.dp),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                if (selected) {
                    Icon(Icons.Rounded.Check, null, tint = GovBlue, modifier = Modifier.size(16.dp))
                    Spacer(Modifier.width(6.dp))
                } else {
                    Box(Modifier.size(8.dp).background(NeutralDot, CircleShape))
                    Spacer(Modifier.width(8.dp))
                }
                Text(
                    model.label,
                    style = MaterialTheme.typography.labelLarge,
                    fontWeight = FontWeight.Bold,
                    color = if (selected) GovBlue else Ink,
                )
            }
        }
    }
}

/** Dropdown selector for attack / distortion type. */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun AttackSelector(
    attacks: List<AttackOption>,
    selectedId: String,
    onSelect: (AttackOption) -> Unit,
    modifier: Modifier = Modifier,
) {
    var expanded by remember { mutableStateOf(false) }
    val selected = attacks.firstOrNull { it.id == selectedId } ?: attacks.first()

    ExposedDropdownMenuBox(
        expanded = expanded,
        onExpandedChange = { expanded = it },
        modifier = modifier,
    ) {
        OutlinedTextField(
            value = selected.label,
            onValueChange = {},
            readOnly = true,
            label = { Text("篡改场景 / 鲁棒性") },
            trailingIcon = { ExposedDropdownMenuDefaults.TrailingIcon(expanded = expanded) },
            shape = RoundedCornerShape(12.dp),
            colors = OutlinedTextFieldDefaults.colors(
                focusedBorderColor = GovBlue,
                unfocusedBorderColor = Divider,
                focusedLabelColor = GovBlue,
                unfocusedLabelColor = InkSecondary,
                focusedTextColor = Ink,
                unfocusedTextColor = Ink,
            ),
            modifier = Modifier
                .menuAnchor(MenuAnchorType.PrimaryNotEditable)
                .fillMaxWidth(),
        )
        DropdownMenu(expanded = expanded, onDismissRequest = { expanded = false }) {
            attacks.forEach { attack ->
                DropdownMenuItem(
                    text = {
                        Column {
                            Text(attack.label, style = MaterialTheme.typography.bodyLarge, color = Ink)
                            Text(attack.category, style = MaterialTheme.typography.labelMedium, color = InkSecondary)
                        }
                    },
                    onClick = {
                        onSelect(attack)
                        expanded = false
                    },
                )
            }
        }
    }
}

/** Single-image picker with gallery + camera, government light styling. */
@Composable
fun ImagePickField(
    selectedUri: Uri?,
    onPicked: (Uri) -> Unit,
    modifier: Modifier = Modifier,
) {
    val context = LocalContext.current
    var cameraUri by rememberSaveable { mutableStateOf<Uri?>(null) }

    val galleryLauncher = rememberLauncherForActivityResult(
        ActivityResultContracts.PickVisualMedia(),
    ) { uri -> if (uri != null) onPicked(uri) }

    val cameraLauncher = rememberLauncherForActivityResult(
        ActivityResultContracts.TakePicture(),
    ) { success -> if (success) cameraUri?.let(onPicked) }

    Column(modifier.fillMaxWidth()) {
        if (selectedUri != null) {
            NetworkImage(
                url = selectedUri.toString(),
                contentDescription = "已选图像",
                modifier = Modifier
                    .fillMaxWidth()
                    .aspectRatio(1.3f)
                    .clip(RoundedCornerShape(14.dp))
                    .border(1.dp, Divider, RoundedCornerShape(14.dp)),
            )
        } else {
            Box(
                modifier = Modifier
                    .fillMaxWidth()
                    .aspectRatio(1.7f)
                    .clip(RoundedCornerShape(14.dp))
                    .background(GovBlueTint.copy(alpha = 0.5f))
                    .marchingAnts(cornerRadius = 14.dp, colorA = GovBlue, colorB = GovBlue),
                contentAlignment = Alignment.Center,
            ) {
                Column(horizontalAlignment = Alignment.CenterHorizontally) {
                    Icon(
                        Icons.Rounded.AddPhotoAlternate,
                        contentDescription = null,
                        tint = GovBlue,
                        modifier = Modifier.size(40.dp),
                    )
                    Spacer(Modifier.height(10.dp))
                    Text("待上传检材 · 支持 JPG / PNG / WEBP", style = MaterialTheme.typography.bodyMedium, color = InkSecondary)
                }
            }
        }

        Spacer(Modifier.height(12.dp))
        Row(horizontalArrangement = Arrangement.spacedBy(12.dp)) {
            SecondaryButton(
                text = "从相册导入",
                icon = Icons.Rounded.PhotoLibrary,
                onClick = {
                    galleryLauncher.launch(PickVisualMediaRequest(ActivityResultContracts.PickVisualMedia.ImageOnly))
                },
                modifier = Modifier.weight(1f),
            )
            SecondaryButton(
                text = "现场拍摄",
                icon = Icons.Rounded.PhotoCamera,
                onClick = {
                    val uri = CaptureUtils.newImageUri(context)
                    cameraUri = uri
                    cameraLauncher.launch(uri)
                },
                modifier = Modifier.weight(1f),
            )
        }
    }
}

/** Multi-image picker for batch compliance checks. */
@Composable
fun MultiImagePickField(
    selected: List<Uri>,
    onPicked: (List<Uri>) -> Unit,
    modifier: Modifier = Modifier,
    maxItems: Int = 9,
) {
    val launcher = rememberLauncherForActivityResult(
        ActivityResultContracts.PickMultipleVisualMedia(maxItems),
    ) { uris -> if (uris.isNotEmpty()) onPicked(uris) }

    Column(modifier.fillMaxWidth()) {
        if (selected.isNotEmpty()) {
            FlowImageStrip(selected)
            Spacer(Modifier.height(12.dp))
        }
        SecondaryButton(
            text = if (selected.isEmpty()) "选择图片（最多 $maxItems 张）" else "已选 ${selected.size} 张 · 重新选择",
            icon = Icons.Rounded.PhotoLibrary,
            onClick = {
                launcher.launch(PickVisualMediaRequest(ActivityResultContracts.PickVisualMedia.ImageOnly))
            },
            modifier = Modifier.fillMaxWidth(),
        )
    }
}

@OptIn(ExperimentalLayoutApi::class)
@Composable
private fun FlowImageStrip(uris: List<Uri>) {
    FlowRow(
        modifier = Modifier.fillMaxWidth(),
        horizontalArrangement = Arrangement.spacedBy(8.dp),
        verticalArrangement = Arrangement.spacedBy(8.dp),
    ) {
        uris.forEach { uri ->
            NetworkImage(
                url = uri.toString(),
                contentDescription = null,
                modifier = Modifier
                    .size(72.dp)
                    .clip(RoundedCornerShape(12.dp))
                    .border(1.dp, Divider, RoundedCornerShape(12.dp)),
            )
        }
    }
}
