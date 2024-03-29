import torch
import torch.nn.functional as F
import torch.optim as optim
import torchvision.models as models
import torchvision.transforms as transforms
from PIL import Image

device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')

img_size = (256, 256)


def read_image(image_path):    
    pipeline = transforms.Compose(
        [transforms.Resize((img_size)),
         transforms.ToTensor()])

    img = Image.open(image_path).convert('RGB')
    img = pipeline(img).unsqueeze(0)
    return img.to(device, torch.float)


def save_image(tensor, image_path):
    toPIL = transforms.ToPILImage()
    img = tensor.detach().cpu().clone()
    img = img.squeeze(0)
    img = toPIL(img)
    img.save(image_path)


# Hyperparameters
style_img = read_image('picasso.jpg')
content_img = read_image('dancing.jpg')

default_content_layers = ['conv_4']
default_style_layers = ['conv_1', 'conv_2', 'conv_3', 'conv_4', 'conv_5']
# 风格损失权重 和 内容损失权重
style_weight = 3
content_weight = 1

# 定义内容损失
class ContentLoss(torch.nn.Module):
    def __init__(self, target: torch.Tensor):
        super().__init__()
        self.target = target.detach()

    def forward(self, input):
        # 均方误差损失函数 sum((a-b)^2)/n 
        # self.loss = F.mse_loss(input, self.target)
        self.loss = 1 - torch.cosine_similarity(input.view(input.shape[1],-1), self.target.view(input.shape[1],-1)).sum() / input.shape[1]
        return input

# 计算x的格里姆矩阵
def gram(x: torch.Tensor):
    # x is a [n, c, h, w] array
    n, c, h, w = x.shape

    features = x.reshape(n * c, h * w)
    features = torch.mm(features, features.T) / n / c / h / w
    return features

# 定义风格损失
class StyleLoss(torch.nn.Module):
    def __init__(self, target: torch.Tensor):
        super().__init__()
        self.target = gram(target.detach()).detach()

    def forward(self, input):
        G = gram(input)
        # 输入和目标的 格里姆矩阵 的 均方损失函数
        # self.loss = F.mse_loss(G, self.target)
        self.loss = 1 - torch.cosine_similarity(G.view(input.shape[1],-1), self.target.view(input.shape[1],-1)).sum() / input.shape[1]
        return input

# 定义 标准化操作
class Normalization(torch.nn.Module):
    def __init__(self, mean, std):
        super().__init__()
        self.mean = torch.tensor(mean).to(device).reshape(-1, 1, 1)
        self.std = torch.tensor(std).to(device).reshape(-1, 1, 1)

    def forward(self, img):
        return (img - self.mean) / self.std


def get_model_and_losses(content_img, style_img, content_layers, style_layers):
    num_loss = 0
    expected_num_loss = len(content_layers) + len(style_layers)
    content_losses = []
    style_losses = []

    model = torch.nn.Sequential(
        Normalization([0.485, 0.456, 0.406], [0.229, 0.224, 0.225]))
    cnn = models.vgg19(pretrained=True).features.to(device).eval()
    i = 0
    for layer in cnn.children():
        if isinstance(layer, torch.nn.Conv2d):
            i += 1
            name = f'conv_{i}'
        elif isinstance(layer, torch.nn.ReLU):
            name = f'relu_{i}'
            layer = torch.nn.ReLU(inplace=False)
        elif isinstance(layer, torch.nn.MaxPool2d):
            name = f'pool_{i}'
        elif isinstance(layer, torch.nn.BatchNorm2d):
            name = f'bn_{i}'
        else:
            raise RuntimeError(
                f'Unrecognized layer: {layer.__class__.__name__}')

        model.add_module(name, layer)

        if name in content_layers:
            # add content loss:
            target = model(content_img)
            content_loss = ContentLoss(target)
            model.add_module(f'content_loss_{i}', content_loss)
            content_losses.append(content_loss)
            num_loss += 1

        if name in style_layers:
            target_feature = model(style_img)
            style_loss = StyleLoss(target_feature)
            model.add_module(f'style_loss_{i}', style_loss)
            style_losses.append(style_loss)
            num_loss += 1

        if num_loss >= expected_num_loss:
            break

    return model, content_losses, style_losses

# 随机生成噪声作为 输入
input_img = torch.randn(1, 3, *img_size, device=device)
model, content_losses, style_losses = get_model_and_losses(
    content_img, style_img, default_content_layers, default_style_layers)

input_img.requires_grad_(True)
model.requires_grad_(False)

optimizer = optim.Adam([input_img])

steps = 0
while steps <= 5000:
    with torch.no_grad():
        input_img.clamp_(0, 1)
    optimizer.zero_grad()
    model(input_img)
    content_loss = 0
    style_loss = 0
    for l in content_losses:
        content_loss += l.loss
    for l in style_losses:
        style_loss += l.loss
    loss = content_weight * content_loss + style_weight * style_loss
    loss.backward()
    steps += 1
    if steps % 1000 == 0:
        print(f'Step {steps}:')
        print(f'Loss: {loss}')

    optimizer.step()

with torch.no_grad():
    input_img.clamp_(0, 1)
save_image(input_img, './output.jpg')
