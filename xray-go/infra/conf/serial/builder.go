package serial

import (
	"context"
	"io"
	"strings"

	"github.com/xtls/xray-core/common/errors"
	creflect "github.com/xtls/xray-core/common/reflect"
	"github.com/xtls/xray-core/core"
	"github.com/xtls/xray-core/infra/conf"
	"github.com/xtls/xray-core/main/confloader"
)

func MergeConfigFromFiles(files []*core.ConfigSource) (string, error) {
	c, err := mergeConfigs(files)
	if err != nil {
		return "", err
	}

	if j, ok := creflect.MarshalToJson(c, true); ok {
		return j, nil
	}
	return "", errors.New("marshal to json failed.").AtError()
}

func mergeConfigs(files []*core.ConfigSource) (*conf.Config, error) {
	cf := &conf.Config{}
	for i, file := range files {
		errors.LogInfo(context.Background(), "Reading config: ", file)
		r, err := confloader.LoadConfig(file.Name)
		if err != nil {
			return nil, errors.New("failed to read config: ", file).Base(err)
		}
		c, err := ReaderDecoderByFormat[file.Format](r)
		if err != nil {
			return nil, errors.New("failed to decode config: ", file).Base(err)
		}
		if i == 0 {
			*cf = *c
			continue
		}
		cf.Override(c, file.Name)
	}
	return cf, nil
}

func BuildConfig(files []*core.ConfigSource) (*core.Config, error) {
	config, err := mergeConfigs(files)
	if err != nil {
		return nil, err
	}
	return config.Build()
}

func BuildConfigFromJSONString(jsonString string) (*core.Config, error) {
	cf := &conf.Config{}
	c, err := DecodeJSONConfig(strings.NewReader(jsonString))
	if err != nil {
		return nil, errors.New("failed to decode JSON config string").Base(err)
	}
	*cf = *c
	return cf.Build()
}

type readerDecoder func(io.Reader) (*conf.Config, error)

var ReaderDecoderByFormat = make(map[string]readerDecoder)

func init() {
	ReaderDecoderByFormat["json"] = DecodeJSONConfig
	ReaderDecoderByFormat["yaml"] = DecodeYAMLConfig
	ReaderDecoderByFormat["toml"] = DecodeTOMLConfig

	core.ConfigBuilderForFiles = BuildConfig
	core.ConfigBuilderForJson = BuildConfigFromJSONString
	core.ConfigMergedFormFiles = MergeConfigFromFiles
}
